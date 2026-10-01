"""Replaceable detector adapter; model loading is cached once per worker process."""

import hashlib
import importlib.metadata
import os
from functools import lru_cache
from pathlib import Path

import numpy as np

from trafficvision.schemas import AnalysisConfig


class YoloDetector:
    def __init__(self, checkpoint: str):
        import torch
        from ultralytics import YOLO

        torch.set_num_threads(max(1, int(os.environ.get("TORCH_NUM_THREADS", "2"))))
        self.model = YOLO(checkpoint)
        self.device = None
        self.names = {int(k): str(v) for k, v in self.model.names.items()}
        self.checkpoint = str(getattr(self.model, "ckpt_path", checkpoint))
        path = Path(self.checkpoint)
        self.sha256 = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

    def validate(self, config: AnalysisConfig):
        import torch

        missing = set(config.classes) - set(self.names.values())
        if missing:
            raise ValueError(f"Checkpoint does not contain requested classes: {sorted(missing)}")
        if config.device.startswith("cuda") and not torch.cuda.is_available():
            raise ValueError(
                "CUDA was requested but is unavailable. Select CPU or configure the GPU worker."
            )
        if self.device != config.device:
            # Ultralytics caches a predictor; .to() clears it when switching run devices.
            self.model.to(config.device)
            self.device = config.device

    def detect(self, image: np.ndarray, config: AnalysisConfig):
        selected = [i for i, name in self.names.items() if name in config.classes]
        # Preserve low-score candidates for ByteTrack's second association stage.
        result = self.model.predict(
            image,
            conf=0.1,
            imgsz=config.image_size,
            device=config.device,
            classes=selected,
            verbose=False,
        )[0]
        return result.boxes.cpu().numpy()

    def metadata(self):
        import torch

        return {
            "adapter": "Ultralytics YOLO",
            "checkpoint": Path(self.checkpoint).name,
            "checkpoint_sha256": self.sha256,
            "class_mapping": self.names,
            "ultralytics_version": importlib.metadata.version("ultralytics"),
            "torch_version": torch.__version__,
            "device": self.device,
            "device_name": torch.cuda.get_device_name(0)
            if self.device == "cuda:0"
            else platform_processor(),
            "torch_threads": torch.get_num_threads(),
        }


def platform_processor():
    import platform

    return platform.processor() or platform.machine()


@lru_cache(maxsize=1)
def get_detector(checkpoint: str | None = None) -> YoloDetector:
    return YoloDetector(checkpoint or os.environ.get("MODEL_CHECKPOINT", "models/yolo11n.pt"))
