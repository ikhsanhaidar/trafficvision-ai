"""Evaluate complete, declared video sets; no model or ground truth is downloaded."""

import argparse
import json
from pathlib import Path

from trafficvision.evaluation import evaluate_count_files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="New report file; must not exist"
    )
    parser.add_argument("--by-line", action="store_true")
    args = parser.parse_args()
    try:
        report = evaluate_count_files(args.ground_truth, args.predictions, by_line=args.by_line)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2, allow_nan=False)
            output.write("\n")
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f"Counting evaluation failed: {exc}\n")
    print(
        json.dumps(
            {
                "report": str(args.output),
                "video_count": report["video_count"],
                "mae_video_total": report["mae_video_total"],
                "mae_video_class_direction": report["mae_video_class_direction"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
