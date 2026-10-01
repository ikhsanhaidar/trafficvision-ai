"""Strict counting evaluation and reproducibility helpers, without loading a model."""

from __future__ import annotations

import hashlib
import json
import platform
from collections import Counter
from importlib.metadata import PackageNotFoundError, version
from itertools import product
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trafficvision.schemas import CrossingEvent, VehicleClass

DIRECTIONS = ("A_to_B", "B_to_A")


class GroundTruthEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    class_name: VehicleClass
    line_id: str = Field(min_length=1)
    direction: Literal["A_to_B", "B_to_A"]
    timestamp_video: float = Field(ge=0, allow_inf_nan=False)


class GroundTruthVideo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_id: str = Field(min_length=1)
    line_ids: list[str] = Field(min_length=1)
    events: list[GroundTruthEvent]

    @model_validator(mode="after")
    def valid_lines(self):
        if any(not line for line in self.line_ids) or len(set(self.line_ids)) != len(self.line_ids):
            raise ValueError("line_ids must be unique and nonempty")
        if any(event.line_id not in self.line_ids for event in self.events):
            raise ValueError("Ground-truth event references an undeclared line")
        return self


class CountingGroundTruth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    classes: list[VehicleClass] = Field(min_length=1)
    videos: list[GroundTruthVideo] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_scope(self):
        if len(set(self.classes)) != len(self.classes):
            raise ValueError("Evaluation classes must be unique")
        if len({video.video_id for video in self.videos}) != len(self.videos):
            raise ValueError("Ground-truth video IDs must be unique")
        if any(
            event.class_name not in self.classes for video in self.videos for event in video.events
        ):
            raise ValueError("Ground-truth event references an unevaluated class")
        return self


class PredictionFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_id: str = Field(min_length=1)
    result: str = Field(min_length=1)


class PredictionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    videos: list[PredictionFile] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_videos(self):
        if len({video.video_id for video in self.videos}) != len(self.videos):
            raise ValueError("Prediction video IDs must be unique")
        return self


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_metadata() -> dict:
    packages = {}
    for package in ("trafficvision-ai", "ultralytics", "torch", "torchvision", "numpy"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    return {
        "python": platform.python_version(),
        "system": platform.platform(),
        "processor": platform.processor(),
        "packages": packages,
    }


def class_mapping(names: dict | list) -> dict[int, str]:
    mapping = (
        dict(enumerate(names))
        if isinstance(names, list)
        else {int(key): value for key, value in names.items()}
    )
    if set(mapping) != set(range(len(mapping))) or len(set(mapping.values())) != len(mapping):
        raise ValueError(
            "Dataset/model names must have unique labels and contiguous zero-based IDs"
        )
    return mapping


def validate_detection_classes(
    dataset_names: dict | list, model_names: dict | list, classes: list[str]
) -> list[int]:
    """Class filtering does not remap label IDs; require an identical label vocabulary."""
    dataset, model = class_mapping(dataset_names), class_mapping(model_names)
    if dataset != model:
        raise ValueError(
            "Dataset and checkpoint class IDs/names differ. Remap annotation IDs and "
            "dataset names explicitly before validation; --classes does not remap IDs."
        )
    if len(set(classes)) != len(classes) or any(label not in dataset.values() for label in classes):
        raise ValueError("Selected evaluation labels must be unique and present in the dataset")
    return [index for index, name in dataset.items() if name in classes]


def snapshot_dataset(data_path: Path, destination: Path, *, split: str = "val") -> dict:
    """Resolve local paths against the input YAML; disallow automatic dataset downloads."""
    import yaml

    dataset = yaml.safe_load(data_path.read_text(encoding="utf-8"))
    if not isinstance(dataset, dict) or "names" not in dataset:
        raise ValueError("Dataset YAML must contain names")
    if "download" in dataset:
        raise ValueError(
            "Remove the dataset download entry: only prepared local datasets are accepted"
        )
    dataset["names"] = class_mapping(dataset["names"])
    root = Path(dataset.get("path", "."))
    root = (data_path.resolve().parent / root).resolve()
    dataset["path"] = str(root)
    for name in {"train", "val", split}:
        value = dataset.get(name)
        if not isinstance(value, str) or "://" in value:
            raise ValueError(f"Dataset {name} must name a local directory or image-list file")
        path = (root / value).resolve()
        if not path.exists():
            raise ValueError(f"Dataset {name} does not exist: {path}")
        dataset[name] = str(path)
    destination.write_text(yaml.safe_dump(dataset, sort_keys=False), encoding="utf-8")
    return dataset


def _event_key(event) -> tuple[str, str, str]:
    return event.class_name, event.line_id, event.direction


def _prediction_counts(result: dict, video: GroundTruthVideo, classes: list[str]) -> Counter:
    """Reject stale summaries, wrong scopes, and duplicate event publication."""
    if result.get("schema_version") != 1:
        raise ValueError(f"{video.video_id}: unsupported result schema_version")
    config = result.get("configuration", {})
    selected_classes = config.get("classes", [])
    if len(selected_classes) != len(classes) or set(selected_classes) != set(classes):
        raise ValueError(f"{video.video_id}: prediction classes differ from evaluation classes")
    line_ids = [line["id"] for line in config.get("lines", [])]
    if len(line_ids) != len(video.line_ids) or set(line_ids) != set(video.line_ids):
        raise ValueError(f"{video.video_id}: prediction lines differ from ground-truth lines")
    if not isinstance(result.get("events"), list):
        raise ValueError(
            f"{video.video_id}: result.json with events is required; summary.json is insufficient"
        )
    counts: Counter = Counter()
    identities = set()
    for raw in result["events"]:
        event = CrossingEvent.model_validate(raw)
        # Reuse finite timestamp and class/line/direction validation.
        GroundTruthEvent.model_validate({key: raw[key] for key in GroundTruthEvent.model_fields})
        if event.class_name not in classes or event.line_id not in video.line_ids:
            raise ValueError(f"{video.video_id}: prediction event is outside the evaluation scope")
        if event.run_id != result.get("run_id"):
            raise ValueError(f"{video.video_id}: event run_id differs from result run_id")
        identity = (event.track_id, event.line_id, event.direction)
        if identity in identities:
            raise ValueError(f"{video.video_id}: duplicate track/line/direction event")
        identities.add(identity)
        counts[_event_key(event)] += 1
    if result.get("crossing_total") != sum(counts.values()):
        raise ValueError(f"{video.video_id}: crossing_total disagrees with events")
    summary: Counter = Counter()
    if not isinstance(result.get("counts"), list):
        raise ValueError(f"{video.video_id}: result counts are required")
    seen = set()
    for row in result["counts"]:
        key = row["class_name"], row["line_id"], row["direction"]
        if key[0] not in classes or key[1] not in video.line_ids or key[2] not in DIRECTIONS:
            raise ValueError(f"{video.video_id}: result count is outside the evaluation scope")
        if key in seen or type(row["count"]) is not int or row["count"] < 0:
            raise ValueError(f"{video.video_id}: invalid or repeated result count")
        seen.add(key)
        summary[key] = row["count"]
    if +summary != +counts:
        raise ValueError(f"{video.video_id}: count summary disagrees with events")
    return counts


def evaluate_counts(
    ground_truth: dict, predictions: dict[str, dict], *, by_line: bool = False
) -> dict:
    """Compute macro MAE over videos, preserving zero-count class/direction rows.

    Totals are aggregated before taking absolute error. Cell errors are also
    reported, because total errors alone can hide class/direction cancellation.
    Optional line MAE averages only videos declaring that line ID.
    """
    truth = CountingGroundTruth.model_validate(ground_truth)
    expected = {video.video_id for video in truth.videos}
    actual = set(predictions)
    if expected != actual:
        raise ValueError(
            f"Prediction video IDs differ: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )
    cells, per_video, per_class, per_direction, per_class_direction = [], [], [], [], []
    line_cells = []
    for video in truth.videos:
        observed = _prediction_counts(predictions[video.video_id], video, truth.classes)
        annotated = Counter(_event_key(event) for event in video.events)

        def row(gt: int, pred: int, **dimensions) -> dict:
            return {
                "video_id": video.video_id,
                **dimensions,
                "ground_truth": gt,
                "predicted": pred,
                "absolute_error": abs(pred - gt),
            }

        video_cells = []
        for cls, direction in product(truth.classes, DIRECTIONS):
            gt = sum(annotated[(cls, line, direction)] for line in video.line_ids)
            pred = sum(observed[(cls, line, direction)] for line in video.line_ids)
            cell = row(gt, pred, class_name=cls, direction=direction)
            cells.append(cell)
            video_cells.append(cell)
            if by_line:
                for line in video.line_ids:
                    key = (cls, line, direction)
                    line_cells.append(
                        row(
                            annotated[key],
                            observed[key],
                            class_name=cls,
                            direction=direction,
                            line_id=line,
                        )
                    )
        total = row(sum(annotated.values()), sum(observed.values()))
        total["mae_class_direction"] = sum(cell["absolute_error"] for cell in video_cells) / len(
            video_cells
        )
        per_video.append(total)

    def aggregate_rows(dimension_names, dimension_values):
        result = []
        for values in dimension_values:
            dimensions = dict(zip(dimension_names, values))
            video_rows = []
            for video in truth.videos:
                matching = [
                    cell
                    for cell in cells
                    if cell["video_id"] == video.video_id
                    and all(cell[key] == value for key, value in dimensions.items())
                ]
                gt = sum(cell["ground_truth"] for cell in matching)
                pred = sum(cell["predicted"] for cell in matching)
                video_rows.append(
                    {
                        "video_id": video.video_id,
                        "ground_truth": gt,
                        "predicted": pred,
                        "absolute_error": abs(pred - gt),
                    }
                )
            result.append(
                {
                    **dimensions,
                    "video_count": len(video_rows),
                    "mae": sum(row["absolute_error"] for row in video_rows) / len(video_rows),
                    "videos": video_rows,
                }
            )
        return result

    per_class = aggregate_rows(["class_name"], ((cls,) for cls in truth.classes))
    per_direction = aggregate_rows(["direction"], ((direction,) for direction in DIRECTIONS))
    per_class_direction = aggregate_rows(
        ["class_name", "direction"], product(truth.classes, DIRECTIONS)
    )
    report = {
        "schema_version": 1,
        "metric": "crossing_count_absolute_error",
        "video_count": len(truth.videos),
        "classes": truth.classes,
        "directions": list(DIRECTIONS),
        "mae_video_total": sum(row["absolute_error"] for row in per_video) / len(per_video),
        "mae_video_class_direction": sum(row["absolute_error"] for row in cells) / len(cells),
        "per_video": per_video,
        "cells": cells,
        "per_class": per_class,
        "per_direction": per_direction,
        "per_class_direction": per_class_direction,
        "notes": [
            "MAE uses every declared video, including videos with no crossings.",
            "Total-count errors can cancel across classes/directions; inspect cells too.",
            "This metric does not match events in time or measure detection/tracking accuracy.",
        ],
    }
    if by_line:
        groups = {}
        for cell in line_cells:
            key = cell["line_id"], cell["class_name"], cell["direction"]
            groups.setdefault(key, []).append(cell["absolute_error"])
        report["line_cells"] = line_cells
        report["per_line_class_direction"] = [
            {
                "line_id": line,
                "class_name": cls,
                "direction": direction,
                "video_count": len(errors),
                "mae": sum(errors) / len(errors),
            }
            for (line, cls, direction), errors in sorted(groups.items())
        ]
    return report


def evaluate_count_files(ground_truth_path: Path, predictions_path: Path, *, by_line=False) -> dict:
    ground_truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    manifest = PredictionManifest.model_validate_json(predictions_path.read_text(encoding="utf-8"))
    predictions, artifacts = {}, []
    paths = set()
    for entry in manifest.videos:
        path = (predictions_path.parent / entry.result).resolve()
        if path in paths:
            raise ValueError("A prediction result file cannot be reused for multiple videos")
        paths.add(path)
        predictions[entry.video_id] = json.loads(path.read_text(encoding="utf-8"))
        artifacts.append(
            {"video_id": entry.video_id, "path": str(path), "sha256": sha256_file(path)}
        )
    report = evaluate_counts(ground_truth, predictions, by_line=by_line)
    report["inputs"] = {
        "ground_truth": {
            "path": str(ground_truth_path.resolve()),
            "sha256": sha256_file(ground_truth_path),
        },
        "predictions_manifest": {
            "path": str(predictions_path.resolve()),
            "sha256": sha256_file(predictions_path),
        },
        "results": artifacts,
    }
    return report
