"""Fine-tune only after a licensed dataset and a compute budget are ready."""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from trafficvision.evaluation import class_mapping, runtime_metadata, sha256_file, snapshot_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument(
        "--checkpoint", type=Path, required=True, help="Trusted local pretrained .pt file"
    )
    parser.add_argument("--output", type=Path, required=True, help="New experiment directory")
    parser.add_argument(
        "--confirm-data-ready",
        action="store_true",
        help="Affirm reviewed licensing, annotations, split isolation and compute budget",
    )
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    args = parser.parse_args()
    if not args.confirm_data_ready:
        parser.error(
            "Training is disabled until --confirm-data-ready is supplied. See docs/ANNOTATION.md."
        )
    if (
        min(args.epochs, args.batch, args.patience) < 1
        or args.image_size < 32
        or args.learning_rate <= 0
    ):
        parser.error(
            "Positive epochs, batch, patience and learning-rate, and image-size >= 32 are required"
        )
    for path in (args.data, args.dataset_manifest, args.checkpoint):
        if not path.is_file():
            parser.error(f"Required local file does not exist: {path}")
    metadata = {
        "schema_version": 1,
        "status": "running",
        "runtime": runtime_metadata(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "arguments": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
        },
        "inputs": {
            key: {"path": str(path.resolve()), "sha256": sha256_file(path)}
            for key, path in (
                ("dataset", args.data),
                ("manifest", args.dataset_manifest),
                ("checkpoint", args.checkpoint),
            )
        },
    }
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        parser.exit(1, f"Cannot create a new experiment directory: {exc}\n")
    started = time.perf_counter()
    try:
        import torch
        from ultralytics import YOLO

        data_path = args.output.resolve() / "dataset.resolved.yaml"
        dataset = snapshot_dataset(args.data, data_path)
        required = {"car", "motorcycle", "bus", "truck"}
        if not required.issubset(set(class_mapping(dataset["names"]).values())):
            raise ValueError("Dataset must declare car, motorcycle, bus and truck labels")
        model = YOLO(str(args.checkpoint.resolve()), task="detect")
        metadata["initial_model_names"] = model.names
        metadata["dataset_names"] = dataset["names"]
        metadata["cuda_device"] = (
            torch.cuda.get_device_name(0)
            if args.device != "cpu" and torch.cuda.is_available()
            else None
        )
        model.train(
            data=str(data_path),
            epochs=args.epochs,
            patience=args.patience,
            imgsz=args.image_size,
            batch=args.batch,
            device=args.device,
            workers=0,
            seed=args.seed,
            deterministic=True,
            amp=False,
            optimizer="AdamW",
            lr0=args.learning_rate,
            cache=False,
            project=str(args.output.resolve()),
            name="training",
            exist_ok=False,
            save=True,
            save_period=1,
            plots=True,
            val=True,
            pretrained=True,
        )
        weights = args.output / "training" / "weights"
        metadata["checkpoints"] = {
            name: {"path": str((weights / name).resolve()), "sha256": sha256_file(weights / name)}
            for name in ("best.pt", "last.pt")
            if (weights / name).is_file()
        }
        metadata["status"] = "succeeded"
        metadata["notes"] = [
            "Model selection uses validation only; evaluate the held-out test split separately.",
            "Seed and deterministic settings do not guarantee bitwise identity across hardware or package versions.",
        ]
    except Exception as exc:
        metadata.update({"status": "failed", "error": str(exc)})
        parser.exit(1, f"Training failed: {exc}\n")
    finally:
        metadata["wall_seconds"] = time.perf_counter() - started
        (args.output / "experiment.json").write_text(
            json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    print(f"Training complete: {args.output / 'experiment.json'}")


if __name__ == "__main__":
    main()
