import argparse
import json
from pathlib import Path

from trafficvision.schemas import AnalysisConfig


def main():
    parser = argparse.ArgumentParser(description="Analyze static-camera traffic video.")
    parser.add_argument("video", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="New output directory, must not exist"
    )
    parser.add_argument("--checkpoint", default=None)
    args = parser.parse_args()
    try:
        from trafficvision.detection import get_detector
        from trafficvision.pipeline import analyze_video

        config = AnalysisConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
        result = analyze_video(
            args.video, args.output, config, detector=get_detector(args.checkpoint)
        )
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "crossings": result["crossing_total"],
                    "throughput_fps": result["throughput_fps"],
                },
                indent=2,
            )
        )
    except KeyboardInterrupt:
        parser.exit(130, "Analysis interrupted; temporary output removed.\n")
    except Exception as exc:
        parser.exit(1, f"Analysis failed: {exc}\n")


if __name__ == "__main__":
    main()
