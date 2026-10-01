"""Explicitly synthetic, locally encoded video fixtures; no real traffic accuracy claims."""

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import pytest


@dataclass(frozen=True)
class SyntheticClip:
    path: Path
    timestamps: tuple[float, ...]
    duration: float
    width: int
    height: int


@pytest.fixture
def synthetic_video(tmp_path):
    """Encode independent fixtures with actual H.264 packets and explicit source PTS."""
    sequence = 0

    def make(
        *,
        timestamps=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5),
        last_duration=0.1,
        width=160,
        height=96,
        start_offset=0.0,
    ):
        import av
        import numpy as np

        nonlocal sequence
        sequence += 1
        path = tmp_path / f"synthetic-{sequence}.mp4"
        timestamps = tuple(timestamps)
        durations = [b - a for a, b in zip(timestamps, timestamps[1:])] + [last_duration]
        time_base = Fraction(1, 1000)
        packet_durations = {}
        with av.open(str(path), "w", format="mp4") as container:
            stream = container.add_stream("libx264", rate=10)
            stream.width, stream.height = width, height
            stream.pix_fmt = "yuv420p"
            stream.time_base = time_base
            stream.codec_context.time_base = time_base
            stream.options = {"preset": "ultrafast", "tune": "zerolatency", "bf": "0"}
            for index, (timestamp, duration) in enumerate(zip(timestamps, durations)):
                image = np.full((height, width, 3), 35 + index * 20, dtype=np.uint8)
                image[height // 4 : height // 2, width // 3 : width // 2] = (20, 130, 230)
                frame = av.VideoFrame.from_ndarray(image, format="bgr24")
                frame.time_base = time_base
                frame.pts = round((timestamp + start_offset) / time_base)
                packet_durations[frame.pts] = round(duration / time_base)
                for packet in stream.encode(frame):
                    packet.duration = packet_durations.pop(packet.pts)
                    container.mux(packet)
            for packet in stream.encode(None):
                packet.duration = packet_durations.pop(packet.pts)
                container.mux(packet)
        assert not packet_durations, "Synthetic fixture lost encoded packet durations"
        return SyntheticClip(path, timestamps, timestamps[-1] + last_duration, width, height)

    return make
