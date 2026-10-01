"""Synthetic evaluation fixtures test metric definitions, not traffic accuracy."""

import copy
import json
from collections import Counter

import pytest
from trafficvision.evaluation import (
    CountingGroundTruth,
    PredictionManifest,
    evaluate_count_files,
    evaluate_counts,
    snapshot_dataset,
    validate_detection_classes,
)


def event(class_name="car", direction="A_to_B", line_id="main", timestamp=1.0):
    return {
        "class_name": class_name,
        "direction": direction,
        "line_id": line_id,
        "timestamp_video": timestamp,
    }


def result(events, *, classes=("car", "truck"), lines=("main",)):
    counts = Counter((row["class_name"], row["line_id"], row["direction"]) for row in events)
    return {
        "schema_version": 1,
        "run_id": "fixture",
        "crossing_total": len(events),
        "configuration": {"classes": list(classes), "lines": [{"id": line} for line in lines]},
        "events": [
            {**row, "run_id": "fixture", "track_id": index} for index, row in enumerate(events)
        ],
        "counts": [
            {"class_name": cls, "line_id": line, "direction": direction, "count": n}
            for (cls, line, direction), n in counts.items()
        ],
    }


def truth(videos):
    return {
        "schema_version": 1,
        "classes": ["car", "truck"],
        "videos": [
            {"video_id": video_id, "line_ids": ["main"], "events": events}
            for video_id, events in videos.items()
        ],
    }


def test_macro_mae_includes_empty_videos_and_all_zero_class_direction_cells():
    # 9 -> 6, 1 -> 2, 0 -> 0: macro total MAE = (3 + 1 + 0) / 3.
    ground_truth = truth({"busy": [event()] * 9, "quiet": [event()], "empty": []})
    predictions = {
        "busy": result([event()] * 6),
        "quiet": result([event()] * 2),
        "empty": result([]),
    }
    report = evaluate_counts(ground_truth, predictions, by_line=True)
    assert report["mae_video_total"] == pytest.approx(4 / 3)
    assert report["mae_video_class_direction"] == pytest.approx(4 / 12)
    assert len(report["cells"]) == 3 * 2 * 2
    assert len(report["line_cells"]) == 3 * 2 * 2
    assert report["per_video"][2]["absolute_error"] == 0
    car = next(row for row in report["per_class"] if row["class_name"] == "car")
    truck = next(row for row in report["per_class"] if row["class_name"] == "truck")
    assert car["mae"] == pytest.approx(4 / 3)
    assert truck["mae"] == 0
    assert truck["video_count"] == 3


def test_total_count_can_cancel_errors_while_cell_metrics_retain_them():
    report = evaluate_counts(truth({"v": [event()]}), {"v": result([event("truck", "B_to_A")])})
    assert report["mae_video_total"] == 0
    assert report["mae_video_class_direction"] == 0.5
    assert all(row["mae"] == 1 for row in report["per_class"])
    assert all(row["mae"] == 1 for row in report["per_direction"])


def test_optional_line_mae_uses_declared_videos_only():
    ground_truth = truth({"v1": [event(line_id="north")], "v2": []})
    ground_truth["videos"][0]["line_ids"] = ["main", "north"]
    report = evaluate_counts(
        ground_truth, {"v1": result([], lines=("main", "north")), "v2": result([])}, by_line=True
    )
    row = next(
        row
        for row in report["per_line_class_direction"]
        if row["line_id"] == "north" and row["class_name"] == "car" and row["direction"] == "A_to_B"
    )
    assert row["video_count"] == 1
    assert row["mae"] == 1
    assert report["mae_video_total"] == 0.5


@pytest.mark.parametrize("predictions", [{}, {"v": result([]), "extra": result([])}])
def test_missing_or_extra_video_predictions_fail(predictions):
    with pytest.raises(ValueError, match="Prediction video IDs differ"):
        evaluate_counts(truth({"v": []}), predictions)


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda data: data.update(crossing_total=4), "crossing_total"),
        (lambda data: data["counts"][0].update(count=4), "summary disagrees"),
        (lambda data: data["configuration"].update(classes=["car"]), "prediction classes"),
        (
            lambda data: data["configuration"].update(lines=[{"id": "different"}]),
            "prediction lines",
        ),
        (lambda data: data["events"][0].update(run_id="other"), "run_id"),
        (lambda data: data["events"].append(copy.deepcopy(data["events"][0])), "duplicate track"),
        (lambda data: data["events"][0].update(timestamp_video=float("nan")), "finite"),
        (lambda data: data.pop("events"), "result.json with events"),
    ],
)
def test_inconsistent_predictions_fail(change, message):
    prediction = result([event()])
    change(prediction)
    with pytest.raises(ValueError, match=message):
        evaluate_counts(truth({"v": [event()]}), {"v": prediction})


def test_duplicate_manifest_videos_are_not_silently_overwritten():
    duplicate = {"schema_version": 1, "videos": [{"video_id": "v", "result": "r.json"}] * 2}
    with pytest.raises(ValueError, match="unique"):
        PredictionManifest.model_validate(duplicate)
    data = truth({"v": []})
    data["videos"].append(copy.deepcopy(data["videos"][0]))
    with pytest.raises(ValueError, match="unique"):
        CountingGroundTruth.model_validate(data)


def test_manifest_paths_are_relative_to_manifest_and_reports_hash_inputs(tmp_path):
    (tmp_path / "r.json").write_text(json.dumps(result([])), encoding="utf-8")
    gt = tmp_path / "gt.json"
    gt.write_text(json.dumps(truth({"v": []})), encoding="utf-8")
    manifest = tmp_path / "predictions.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "videos": [{"video_id": "v", "result": "r.json"}]}),
        encoding="utf-8",
    )
    report = evaluate_count_files(gt, manifest)
    assert report["mae_video_total"] == 0
    assert len(report["inputs"]["results"][0]["sha256"]) == 64
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "videos": [
                    {"video_id": "v", "result": "r.json"},
                    {"video_id": "v2", "result": "r.json"},
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="reused"):
        evaluate_count_files(gt, manifest)


def test_checkpoint_and_dataset_ids_must_match_not_just_names():
    with pytest.raises(ValueError, match="class IDs/names differ"):
        validate_detection_classes(["car", "truck"], ["truck", "car"], ["car"])
    with pytest.raises(ValueError, match="class IDs/names differ"):
        validate_detection_classes(["car", "truck"], ["person", "car", "truck"], ["car", "truck"])
    assert validate_detection_classes(
        ["person", "car", "truck"], {0: "person", 1: "car", 2: "truck"}, ["truck", "car"]
    ) == [1, 2]


def test_dataset_paths_resolve_from_yaml_and_downloads_are_refused(tmp_path):
    for split in ("train", "val", "test"):
        (tmp_path / "dataset" / "images" / split).mkdir(parents=True)
    source = tmp_path / "data.yaml"
    source.write_text(
        "path: dataset\ntrain: images/train\nval: images/val\ntest: images/test\nnames: [car, truck]\n",
        encoding="utf-8",
    )
    resolved = snapshot_dataset(source, tmp_path / "resolved.yaml", split="test")
    assert resolved["test"] == str(tmp_path / "dataset" / "images" / "test")
    with source.open("a", encoding="utf-8") as stream:
        stream.write("download: https://example.invalid/data.zip\n")
    with pytest.raises(ValueError, match="download"):
        snapshot_dataset(source, tmp_path / "rejected.yaml")
