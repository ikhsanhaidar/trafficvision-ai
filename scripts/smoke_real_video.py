"""Opt-in real-checkpoint smoke test on the checksum-verified CC BY 3.0 video."""

import argparse
import json
from pathlib import Path

from fetch_smoke_video import SOURCE, fetch
from trafficvision.pipeline import analyze_video
from trafficvision.schemas import AnalysisConfig
from trafficvision.video_io import probe_video


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/real-video-smoke"))
    parser.add_argument("--config", type=Path, default=Path("examples/analysis.json"))
    parser.add_argument("--checkpoint", default="models/yolo11n.pt")
    args = parser.parse_args()
    from trafficvision.detection import get_detector

    source = fetch(Path("data/smoke/gothenburg.ogv"))
    config = AnalysisConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
    source_info = probe_video(source, Path("artifacts/smoke-preview.jpg"))
    result = analyze_video(
        source, args.output, config, detector=get_detector(args.checkpoint), video_info=source_info
    )
    exported = json.loads((args.output / "result.json").read_text(encoding="utf-8"))
    assert len(exported["events"]) == result["crossing_total"]
    keys = {(e["track_id"], e["line_id"], e["direction"]) for e in exported["events"]}
    assert len(keys) == result["crossing_total"], "Duplicate crossing events"
    output_info = probe_video(args.output / "annotated.mp4")
    assert output_info.frame_count == source_info.frame_count
    assert abs(output_info.duration_seconds - source_info.duration_seconds) <= 1 / source_info.fps
    attribution = {
        **SOURCE,
        "changes": "Bounding boxes, track IDs, counting lines, statistics and timestamp overlays added. Audio omitted.",
    }
    (args.output / "source-attribution.json").write_text(
        json.dumps(attribution, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "source_frames": source_info.frame_count,
                "video_seconds": source_info.duration_seconds,
                "processing_seconds": result["processing_seconds"],
                "throughput_fps": result["throughput_fps"],
                "crossing_events": result["crossing_total"],
                "accuracy_evaluated": False,
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
