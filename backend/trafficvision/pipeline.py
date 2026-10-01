"""Streaming pipeline with cooperative cancellation and atomic directory publication."""

import csv
import json
import os
import platform
import shutil
import time
import uuid
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from trafficvision.counting import CrossingCounter
from trafficvision.detection import get_detector
from trafficvision.schemas import AnalysisConfig, VideoInfo
from trafficvision.tracking import ByteTrackAdapter
from trafficvision.video_io import VideoWriter, frames, probe_video


class AnalysisCanceled(Exception):
    pass


def annotate(image, observations, counter, config, timestamp, count):
    height, width = image.shape[:2]
    for item in observations:
        x1, y1, x2, y2 = map(int, item.bbox)
        cv2.rectangle(image, (x1, y1), (x2, y2), (120, 220, 70), 2)
        label = counter.class_name(item.track_id) or item.class_name
        cv2.putText(
            image,
            f"{label} #{item.track_id}",
            (x1, max(18, y1 - 7)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (120, 220, 70),
            1,
        )
        cv2.circle(image, ((x1 + x2) // 2, y2), 3, (0, 220, 255), -1)
    if config.roi:
        points = np.array([(round(p.x * width), round(p.y * height)) for p in config.roi], np.int32)
        cv2.polylines(image, [points], True, (220, 170, 30), 2)
    for line in config.lines:
        start = (round(line.start.x * width), round(line.start.y * height))
        end = (round(line.end.x * width), round(line.end.y * height))
        cv2.arrowedLine(image, start, end, (0, 200, 255), 2, tipLength=0.04)
        cv2.putText(image, line.id, start, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)
    cv2.rectangle(image, (0, 0), (min(width, 450), 30), (24, 32, 40), -1)
    cv2.putText(
        image,
        f"TrafficVision | {timestamp:.2f}s | Crossings: {count}",
        (8, 21),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (240, 240, 240),
        1,
    )
    return image


def analyze_video(
    source: Path,
    output_dir: Path,
    config: AnalysisConfig,
    run_id: str | None = None,
    *,
    detector=None,
    tracker_factory=ByteTrackAdapter,
    progress=None,
    canceled=None,
    video_info: VideoInfo | None = None,
) -> dict:
    """Result directory is immutable. Callers choose an attempt-specific destination."""
    started = time.perf_counter()
    run_id = run_id or str(uuid.uuid4())
    if output_dir.exists():
        raise FileExistsError("Result destination already exists; use a new run ID.")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_dir.parent / f".{output_dir.name}.{uuid.uuid4().hex}.tmp"
    temporary.mkdir()
    writer = None
    try:
        if canceled and canceled():
            raise AnalysisCanceled("Analysis canceled.")
        if progress:
            progress(0.0, 0)
        info = video_info or probe_video(source)
        detector = detector or get_detector()
        detector.validate(config)
        tracker = tracker_factory(config, info.fps, detector.names)
        counter = CrossingCounter(config, run_id, info.width, info.height)
        writer = VideoWriter(temporary / "annotated.mp4", info)
        totals: Counter = Counter()
        interval_counts: Counter = Counter()
        count = 0
        frame_count = 0
        inference_seconds = 0.0
        pending = None
        with (
            (temporary / "events.jsonl").open("w", encoding="utf-8") as event_file,
            (temporary / "events.csv").open("w", encoding="utf-8", newline="") as csv_file,
        ):
            csv_writer = csv.DictWriter(
                csv_file,
                fieldnames=[
                    "run_id",
                    "track_id",
                    "class_name",
                    "line_id",
                    "direction",
                    "timestamp_video",
                ],
            )
            csv_writer.writeheader()
            for frame_count, frame in enumerate(frames(source), 1):
                if canceled and canceled():
                    raise AnalysisCanceled("Analysis canceled.")
                inference_start = time.perf_counter()
                observations = tracker.update(detector.detect(frame.image, config), frame.image)
                inference_seconds += time.perf_counter() - inference_start
                events = counter.update(observations, frame.timestamp, frame_count)
                for event in events:
                    data = event.model_dump()
                    event_file.write(json.dumps(data) + "\n")
                    csv_writer.writerow(data)
                    totals[(event.class_name, event.line_id, event.direction)] += 1
                    interval_counts[
                        (int(event.timestamp_video // 10) * 10, event.class_name, event.direction)
                    ] += 1
                    count += 1
                rendered = annotate(
                    frame.image, observations, counter, config, frame.timestamp, count
                )
                if pending:
                    writer.write(pending[0], pending[1], frame.timestamp - pending[1])
                pending = (rendered, frame.timestamp, frame.duration)
                if progress:
                    progress(
                        min(0.99, (frame.timestamp + frame.duration) / info.duration_seconds),
                        frame_count,
                    )
            if pending:
                writer.write(*pending)
            writer.close()
        if canceled and canceled():
            raise AnalysisCanceled("Analysis canceled.")
        # Verify the encoded artifact can actually be decoded before making it visible.
        result_info = probe_video(temporary / "annotated.mp4")
        if result_info.frame_count != frame_count or abs(
            result_info.duration_seconds - info.duration_seconds
        ) > max(0.002, 1 / info.fps):
            raise RuntimeError("Encoded result timing or frame count differs from source.")
        elapsed = time.perf_counter() - started
        result = {
            "schema_version": 1,
            "run_id": run_id,
            "video": info.model_dump(),
            "configuration": config.model_dump(),
            "model": detector.metadata(),
            "tracker": {
                "name": "ByteTrack",
                "high_threshold": config.confidence,
                "low_threshold": 0.1,
                "match_threshold": 0.8,
                "track_buffer": config.max_track_gap,
            },
            "hardware": {
                "system": platform.platform(),
                "processor": platform.processor(),
                "device": config.device,
                "cpu_count": os.cpu_count(),
            },
            "processing_seconds": elapsed,
            "inference_seconds": inference_seconds,
            "processed_frames": frame_count,
            "throughput_fps": frame_count / elapsed,
            "crossing_total": count,
            "counts": [
                {"class_name": cls, "line_id": line, "direction": direction, "count": n}
                for (cls, line, direction), n in sorted(totals.items())
            ],
            "interval_seconds": 10,
            "intervals": [
                {"start_seconds": sec, "class_name": cls, "direction": direction, "count": n}
                for (sec, cls, direction), n in sorted(interval_counts.items())
            ],
            "notes": [
                "Crossings, not unique vehicles; ID switches can cause error.",
                "Audio omitted. Source frame PTS preserved; odd dimensions padded by one pixel.",
            ],
        }
        # Stream the JSON export instead of accumulating all events in memory.
        with (temporary / "result.json").open("w", encoding="utf-8") as export:
            export.write(json.dumps(result)[:-1] + ', "events": [')
            with (temporary / "events.jsonl").open(encoding="utf-8") as events:
                for index, line in enumerate(events):
                    if index:
                        export.write(",")
                    export.write(line.strip())
            export.write("]}")
        (temporary / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        if canceled and canceled():
            raise AnalysisCanceled("Analysis canceled.")
        if progress:
            progress(1.0, frame_count)
        temporary.rename(output_dir)
        return result
    except BaseException:
        if writer:
            writer.abort()
        shutil.rmtree(temporary, ignore_errors=True)
        raise
