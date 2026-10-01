"""Run real bounding-box validation with a local checkpoint and prepared annotations."""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from trafficvision.evaluation import (
    runtime_metadata,
    sha256_file,
    snapshot_dataset,
    validate_detection_classes,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        required=True,
        help="Versioned split/provenance manifest; see docs/ANNOTATION.md",
    )
    parser.add_argument(
        "--checkpoint", type=Path, required=True, help="Trusted local .pt checkpoint"
    )
    parser.add_argument("--output", type=Path, required=True, help="New experiment directory")
    parser.add_argument("--split", choices=["val", "test"], default="test")
    parser.add_argument("--classes", nargs="+", default=["car", "motorcycle", "bus", "truck"])
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.001,
        help="Candidate threshold for PR/AP sweep, not the dashboard's operating threshold",
    )
    parser.add_argument("--nms-iou", type=float, default=0.7)
    args = parser.parse_args()
    if (
        args.image_size < 32
        or args.batch < 1
        or not 0 < args.confidence < 1
        or not 0 < args.nms_iou < 1
    ):
        parser.error(
            "image-size >= 32, batch >= 1 and thresholds strictly between 0 and 1 are required"
        )
    for path in (args.data, args.dataset_manifest, args.checkpoint):
        if not path.is_file():
            parser.error(f"Required local file does not exist: {path}")
    metadata = {
        "schema_version": 1,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "runtime": runtime_metadata(),
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
        from ultralytics.utils.torch_utils import init_seeds

        data_path = args.output.resolve() / "dataset.resolved.yaml"
        dataset = snapshot_dataset(args.data, data_path, split=args.split)
        model = YOLO(str(args.checkpoint.resolve()), task="detect")
        class_ids = validate_detection_classes(dataset["names"], model.names, args.classes)
        init_seeds(args.seed, deterministic=True)
        metadata["model_names"] = model.names
        metadata["cuda_device"] = (
            torch.cuda.get_device_name(0)
            if args.device != "cpu" and torch.cuda.is_available()
            else None
        )
        metrics = model.val(
            data=str(data_path),
            split=args.split,
            classes=class_ids,
            device=args.device,
            imgsz=args.image_size,
            batch=args.batch,
            workers=0,
            seed=args.seed,
            deterministic=True,
            half=False,
            conf=args.confidence,
            iou=args.nms_iou,
            project=str(args.output.resolve()),
            name="validation",
            exist_ok=False,
            plots=True,
            save_json=False,
            verbose=False,
        )
        measured_classes = {
            int(class_id): index for index, class_id in enumerate(metrics.box.ap_class_index)
        }
        if metrics.nt_per_class is None or not sum(
            int(metrics.nt_per_class[index]) for index in class_ids
        ):
            raise ValueError(
                "No ground-truth instances for selected classes; detection accuracy is undefined"
            )
        per_class = []
        for class_id in class_ids:
            index = measured_classes.get(class_id)
            instances = int(metrics.nt_per_class[class_id])
            row = {
                "class_id": class_id,
                "class_name": model.names[class_id],
                "ground_truth_instances": instances,
            }
            if not instances:
                row.update(
                    {
                        "status": "no_ground_truth_instances",
                        "precision": None,
                        "recall": None,
                        "map50": None,
                        "map50_95": None,
                    }
                )
            elif index is None:
                raise ValueError(f"Validator returned no metrics for annotated class {class_id}")
            else:
                row.update(
                    {
                        "status": "measured",
                        "precision": float(metrics.box.p[index]),
                        "recall": float(metrics.box.r[index]),
                        "map50": float(metrics.box.ap50[index]),
                        "map50_95": float(metrics.box.ap[index]),
                    }
                )
            per_class.append(row)
        metadata.update(
            {
                "status": "succeeded",
                "metrics": {
                    "precision": float(metrics.box.mp),
                    "recall": float(metrics.box.mr),
                    "map50": float(metrics.box.map50),
                    "map50_95": float(metrics.box.map),
                    "per_class": per_class,
                },
                "speed_ms_per_image": {key: float(value) for key, value in metrics.speed.items()},
                "precision_recall_definition": "Ultralytics max-F1 operating point on the confidence sweep; not fixed-threshold P/R",
                "notes": [
                    "Absent ground-truth classes have null per-class metrics, not fabricated zero accuracy.",
                    "Model validation timing excludes full video decode, tracking, overlays and encoding.",
                    "Dataset split/provenance manifest is hashed; its content still requires human review.",
                ],
            }
        )
    except Exception as exc:
        metadata.update({"status": "failed", "error": str(exc)})
        parser.exit(1, f"Detection evaluation failed: {exc}\n")
    finally:
        metadata["wall_seconds"] = time.perf_counter() - started
        (args.output / "evaluation.json").write_text(
            json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    print(f"Measured detection report: {args.output / 'evaluation.json'}")


if __name__ == "__main__":
    main()
