"""Synthetic integration tests of media I/O and pipeline contracts, without model downloads."""

import csv
import json

import numpy as np
import pytest
from trafficvision import pipeline
from trafficvision.pipeline import AnalysisCanceled, analyze_video
from trafficvision.schemas import AnalysisConfig, CountLine, Point, TrackObservation
from trafficvision.video_io import VideoError, VideoLimits, frames, probe_video

TIMELINES = [
    pytest.param((0.0, 0.1, 0.2, 0.3, 0.4, 0.5), 0.1, id="synthetic-cfr"),
    pytest.param((0.0, 0.04, 0.11, 0.25, 0.28, 0.51), 0.09, id="synthetic-vfr"),
]


class SyntheticDetector:
    """Stateless detections shared between runs, explicitly not a trained inference test."""

    names = {2: "car", 7: "truck"}

    def __init__(self):
        self.calls = 0
        self.validated = []

    def validate(self, config):
        self.validated.append(config)

    def detect(self, image, config):
        self.calls += 1
        return {"shape": image.shape, "classes": config.classes}

    def metadata(self):
        return {
            "adapter": "Synthetic test detector",
            "checkpoint": None,
            "class_mapping": self.names,
        }


class SyntheticTrackerFactory:
    def __init__(self):
        self.instances = []

    def __call__(self, config, fps, names):
        assert config.classes == ["car"]
        assert fps > 0
        assert names[2] == "car"
        tracker = SyntheticTracker()
        self.instances.append(tracker)
        return tracker


class SyntheticTracker:
    def __init__(self):
        self.updates = 0

    def update(self, boxes, image):
        assert boxes == {"shape": image.shape, "classes": ["car"]}
        bottom = [24, 36, 60, 72, 60, 24][self.updates]
        self.updates += 1
        return [
            TrackObservation(
                track_id=1, class_name="car", confidence=0.95, bbox=(60, bottom - 20, 100, bottom)
            )
        ]


@pytest.fixture
def analysis_config():
    return AnalysisConfig(
        classes=["car"],
        min_track_age=2,
        hysteresis=0.005,
        lines=[CountLine(id="main", start=Point(x=0.1, y=0.5), end=Point(x=0.9, y=0.5))],
    )


@pytest.mark.parametrize(("timestamps", "last_duration"), TIMELINES)
def test_probe_retains_real_encoded_source_timestamps_and_duration(
    synthetic_video,
    tmp_path,
    timestamps,
    last_duration,
):
    clip = synthetic_video(timestamps=timestamps, last_duration=last_duration)
    preview = tmp_path / "preview" / "first.jpg"
    info = probe_video(clip.path, preview)
    decoded = list(frames(clip.path))

    assert info.frame_count == len(timestamps)
    assert (info.width, info.height) == (clip.width, clip.height)
    assert info.duration_seconds == pytest.approx(clip.duration, abs=0.001)
    assert info.timing == "source_pts"
    assert info.codec == "h264"
    assert info.size_bytes == clip.path.stat().st_size
    assert preview.is_file() and preview.stat().st_size > 0
    assert [frame.timestamp for frame in decoded] == pytest.approx(timestamps, abs=0.001)
    assert decoded[-1].duration == pytest.approx(last_duration, abs=0.001)
    assert all(frame.source_pts for frame in decoded)


def test_source_timestamp_offset_is_normalized_to_video_start(synthetic_video):
    clip = synthetic_video(start_offset=2.0)
    decoded = list(frames(clip.path))
    assert [frame.timestamp for frame in decoded] == pytest.approx(clip.timestamps, abs=0.001)
    assert probe_video(clip.path).duration_seconds == pytest.approx(clip.duration, abs=0.001)


@pytest.mark.parametrize("content", [b"", b"This is corrupt data, not an encoded video."])
def test_empty_and_corrupt_uploads_fail_with_actionable_error(tmp_path, content):
    source = tmp_path / "upload.mp4"
    source.write_bytes(content)
    message = "empty or missing" if not content else "Video decoding failed"
    with pytest.raises(VideoError, match=message):
        probe_video(source)


def test_missing_source_is_rejected(tmp_path):
    with pytest.raises(VideoError, match="empty or missing"):
        probe_video(tmp_path / "missing.mp4")


@pytest.mark.parametrize(
    ("limits", "message"),
    [
        (VideoLimits(max_bytes=1), "upload size limit"),
        (VideoLimits(max_dimension=32), "resolution"),
        (VideoLimits(max_pixels=100), "resolution"),
        (VideoLimits(max_duration=0.2), "duration or decoded frame limits"),
        (VideoLimits(max_frames=2), "duration or decoded frame limits"),
    ],
)
def test_validation_enforces_limits_while_decoding(synthetic_video, limits, message):
    clip = synthetic_video()
    with pytest.raises(VideoError, match=message):
        probe_video(clip.path, limits=limits)


@pytest.mark.parametrize(("timestamps", "last_duration"), TIMELINES)
def test_analysis_writes_consistent_exports_and_preserves_annotated_timing(
    synthetic_video,
    tmp_path,
    analysis_config,
    timestamps,
    last_duration,
):
    clip = synthetic_video(timestamps=timestamps, last_duration=last_duration)
    output = tmp_path / "results" / "synthetic-run"
    detector, factory, updates = SyntheticDetector(), SyntheticTrackerFactory(), []
    result = analyze_video(
        clip.path,
        output,
        analysis_config,
        run_id="synthetic-run",
        detector=detector,
        tracker_factory=factory,
        progress=lambda progress, count: updates.append((progress, count)),
    )
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    exported = json.loads((output / "result.json").read_text(encoding="utf-8"))
    events = [json.loads(row) for row in (output / "events.jsonl").read_text().splitlines()]
    with (output / "events.csv").open(encoding="utf-8", newline="") as stream:
        csv_events = list(csv.DictReader(stream))

    assert summary == json.loads(json.dumps(result))
    assert exported == {**summary, "events": events}
    assert len(events) == len(csv_events) == result["crossing_total"] == 2
    assert [event["direction"] for event in events] == ["A_to_B", "B_to_A"]
    # Crossing time interpolates source timestamps at the actual line intersection.
    assert [event["timestamp_video"] for event in events] == pytest.approx(
        [
            (timestamps[1] + timestamps[2]) / 2,
            timestamps[4] + (timestamps[5] - timestamps[4]) / 3,
        ]
    )
    for event, csv_event in zip(events, csv_events):
        assert event["run_id"] == "synthetic-run"
        assert event["track_id"] == 1
        assert event["class_name"] == "car"
        assert event["line_id"] == "main"
        assert csv_event == {key: str(value) for key, value in event.items()}
    assert result["counts"] == [
        {"class_name": "car", "line_id": "main", "direction": "A_to_B", "count": 1},
        {"class_name": "car", "line_id": "main", "direction": "B_to_A", "count": 1},
    ]
    assert sum(interval["count"] for interval in result["intervals"]) == 2
    assert result["processed_frames"] == len(timestamps)
    assert result["processing_seconds"] > 0
    assert 0 <= result["inference_seconds"] <= result["processing_seconds"]
    assert result["throughput_fps"] == pytest.approx(len(timestamps) / result["processing_seconds"])
    assert result["model"]["adapter"] == "Synthetic test detector"
    assert result["configuration"] == analysis_config.model_dump()
    assert detector.calls == len(timestamps)
    assert detector.validated == [analysis_config]
    assert len(factory.instances) == 1 and factory.instances[0].updates == len(timestamps)
    assert updates[0] == (0, 0) and updates[-1] == (1, len(timestamps))
    assert all(a[0] <= b[0] for a, b in zip(updates, updates[1:]))

    annotated = list(frames(output / "annotated.mp4"))
    assert [frame.timestamp for frame in annotated] == pytest.approx(timestamps, abs=0.001)
    assert probe_video(output / "annotated.mp4").duration_seconds == pytest.approx(
        clip.duration,
        abs=0.001,
    )
    source_first = next(frames(clip.path)).image
    assert np.mean(np.abs(annotated[0].image.astype(float) - source_first)) > 5
    assert list(output.parent.iterdir()) == [output], "Temporary artifacts must not remain"


def test_reusing_detector_keeps_tracker_and_counting_state_isolated(
    synthetic_video,
    tmp_path,
    analysis_config,
):
    clip = synthetic_video()
    detector, factory = SyntheticDetector(), SyntheticTrackerFactory()
    exports = []
    for run_id in ("first", "second"):
        output = tmp_path / run_id
        analyze_video(
            clip.path,
            output,
            analysis_config,
            run_id=run_id,
            detector=detector,
            tracker_factory=factory,
        )
        exports.append(json.loads((output / "result.json").read_text()))

    assert len(factory.instances) == 2
    assert factory.instances[0] is not factory.instances[1]
    assert [instance.updates for instance in factory.instances] == [6, 6]
    assert detector.calls == 12
    assert [export["crossing_total"] for export in exports] == [2, 2]
    for run_id, export in zip(("first", "second"), exports):
        assert {event["run_id"] for event in export["events"]} == {run_id}
    events_without_run = [
        [
            {key: value for key, value in event.items() if key != "run_id"}
            for event in export["events"]
        ]
        for export in exports
    ]
    assert events_without_run[0] == events_without_run[1]


@pytest.mark.parametrize(
    "cancel_after", [0, 2, 6], ids=["before-start", "mid-video", "after-encoding"]
)
def test_cancellation_never_publishes_partial_results(
    synthetic_video,
    tmp_path,
    analysis_config,
    cancel_after,
):
    clip = synthetic_video()
    output = tmp_path / "results" / "canceled"
    detector = SyntheticDetector()
    with pytest.raises(AnalysisCanceled, match="canceled"):
        analyze_video(
            clip.path,
            output,
            analysis_config,
            detector=detector,
            tracker_factory=SyntheticTrackerFactory(),
            canceled=lambda: detector.calls >= cancel_after,
        )
    assert detector.calls == cancel_after
    assert not output.exists()
    assert list(output.parent.iterdir()) == []
    assert probe_video(clip.path).frame_count == 6


def test_encoder_failure_cleans_up_output(synthetic_video, tmp_path, analysis_config, monkeypatch):
    clip = synthetic_video()
    output = tmp_path / "results" / "broken-encoder"
    writer_class = pipeline.VideoWriter

    class FailingWriter(writer_class):
        def write(self, image, timestamp, duration):
            super().write(image, timestamp, duration)
            raise RuntimeError("Synthetic encoder failure")

    monkeypatch.setattr(pipeline, "VideoWriter", FailingWriter)
    with pytest.raises(RuntimeError, match="Synthetic encoder failure"):
        analyze_video(
            clip.path,
            output,
            analysis_config,
            detector=SyntheticDetector(),
            tracker_factory=SyntheticTrackerFactory(),
        )
    assert not output.exists()
    assert list(output.parent.iterdir()) == []


def test_existing_result_is_immutable(synthetic_video, tmp_path, analysis_config):
    clip = synthetic_video()
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "result.json"
    marker.write_text('{"existing": true}', encoding="utf-8")
    detector = SyntheticDetector()
    with pytest.raises(FileExistsError, match="already exists"):
        analyze_video(
            clip.path,
            output,
            analysis_config,
            detector=detector,
            tracker_factory=SyntheticTrackerFactory(),
        )
    assert marker.read_text() == '{"existing": true}'
    assert detector.calls == 0
    assert list(output.iterdir()) == [marker]


def test_final_progress_failure_does_not_publish_result(
    synthetic_video,
    tmp_path,
    analysis_config,
):
    clip = synthetic_video()
    output = tmp_path / "results" / "failed-progress"
    updates = []

    def unavailable_progress(progress, count):
        updates.append((progress, count))
        if progress == 1:
            raise RuntimeError("Synthetic progress persistence failure")

    with pytest.raises(RuntimeError, match="Synthetic progress persistence failure"):
        analyze_video(
            clip.path,
            output,
            analysis_config,
            detector=SyntheticDetector(),
            tracker_factory=SyntheticTrackerFactory(),
            progress=unavailable_progress,
        )

    assert updates[-1] == (1, 6)
    assert not output.exists()
    assert list(output.parent.iterdir()) == []
