"""Trim the licensed real smoke footage to eight seconds for browser workflow checks."""

import json
from pathlib import Path

from fetch_smoke_video import SOURCE, fetch
from trafficvision.video_io import VideoWriter, frames, probe_video


def main():
    source = fetch(Path("data/smoke/gothenburg.ogv"))
    output = Path("artifacts/browser/source.mp4")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        info = probe_video(output)
        if 7.9 <= info.duration_seconds <= 8.1:
            print(f"Verified existing real browser clip: {info.frame_count} frames")
            return
        raise SystemExit(
            "Existing browser clip has unexpected duration; inspect it before replacing."
        )
    info = probe_video(source)
    temporary = output.with_suffix(".part.mp4")
    writer = VideoWriter(temporary, info)
    count = 0
    try:
        for frame in frames(source):
            if frame.timestamp >= 8:
                break
            writer.write(frame.image, frame.timestamp, frame.duration)
            count += 1
        writer.close()
        clipped = probe_video(temporary)
        if not 7.9 <= clipped.duration_seconds <= 8.1 or clipped.frame_count != count:
            raise RuntimeError("Browser clip timing or frame count is incorrect.")
        temporary.replace(output)
        attribution = {
            **SOURCE,
            "changes": "Trimmed to first eight seconds; re-encoded as H.264 MP4; audio omitted.",
            "output_frame_count": count,
            "output_duration_seconds": clipped.duration_seconds,
        }
        output.with_suffix(".source.json").write_text(
            json.dumps(attribution, indent=2), encoding="utf-8"
        )
        print(f"Prepared real browser clip: {count} frames, {clipped.duration_seconds:.3f}s")
    except BaseException:
        writer.abort()
        temporary.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
