"""Bounded FFmpeg I/O through PyAV, retaining presentation timing."""

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av
import cv2
import numpy as np

from trafficvision.schemas import VideoInfo


class VideoError(ValueError):
    pass


@dataclass(frozen=True)
class VideoLimits:
    max_bytes: int = 500 * 1024 * 1024
    max_duration: float = 900
    max_dimension: int = 3840
    max_pixels: int = 3840 * 2160
    max_frames: int = 108000


@dataclass
class DecodedFrame:
    image: np.ndarray
    timestamp: float
    duration: float
    source_pts: bool


def frames(path: Path, limits: VideoLimits = VideoLimits()):
    """Decode one frame at a time. Reject ambiguous, nonmonotonic and excessive media."""
    if not path.is_file() or path.stat().st_size == 0:
        raise VideoError("The video is empty or missing.")
    if path.stat().st_size > limits.max_bytes:
        raise VideoError("Video exceeds the upload size limit.")
    try:
        with av.open(str(path)) as container:
            if not container.streams.video:
                raise VideoError("No decodable video stream was found.")
            stream = container.streams.video[0]
            if str(stream.metadata.get("rotate", "0")) not in ("0", "0.0"):
                raise VideoError("Rotated video must be normalized before upload.")
            fps = float(stream.average_rate or stream.base_rate or stream.guessed_rate or 0)
            if not 0 < fps <= 120:
                raise VideoError("Video must have a valid frame rate between 0 and 120 FPS.")
            first_time, previous, shape, uses_pts = None, -1.0, None, None
            count = 0
            for count, frame in enumerate(container.decode(stream), 1):
                w, h = frame.width, frame.height
                if (
                    w < 16
                    or h < 16
                    or max(w, h) > limits.max_dimension
                    or w * h > limits.max_pixels
                ):
                    raise VideoError("Video resolution is outside the supported limits.")
                if getattr(frame, "rotation", 0):
                    raise VideoError("Rotated video must be normalized before upload.")
                if shape and shape != (w, h):
                    raise VideoError("Changing frame dimensions are not supported.")
                shape = (w, h)
                has_pts = frame.pts is not None and frame.time_base is not None
                if uses_pts is not None and uses_pts != has_pts:
                    raise VideoError("Video contains inconsistent presentation timestamps.")
                uses_pts = has_pts
                raw_time = float(frame.pts * frame.time_base) if has_pts else (count - 1) / fps
                if first_time is None:
                    first_time = raw_time
                timestamp = raw_time - first_time
                duration = (
                    float(frame.duration * frame.time_base)
                    if frame.duration and frame.time_base
                    else 1 / fps
                )
                if timestamp <= previous:
                    raise VideoError("Video presentation timestamps must increase monotonically.")
                if timestamp + duration > limits.max_duration + 0.001 or count > limits.max_frames:
                    raise VideoError("Video exceeds duration or decoded frame limits.")
                previous = timestamp
                yield DecodedFrame(frame.to_ndarray(format="bgr24"), timestamp, duration, has_pts)
            if count == 0:
                raise VideoError("Video has no decodable frames.")
    except (av.FFmpegError, OSError) as exc:
        raise VideoError(f"Video decoding failed: {exc}") from exc


def probe_video(
    path: Path, preview_path: Path | None = None, limits: VideoLimits = VideoLimits()
) -> VideoInfo:
    """Validate the entire stream, including late corruption; memory stays one frame."""
    count, last, first = 0, None, None
    for frame in frames(path, limits):
        if first is None:
            first = frame
            if preview_path:
                preview_path.parent.mkdir(parents=True, exist_ok=True)
                if not cv2.imwrite(str(preview_path), frame.image):
                    raise VideoError("Could not write video preview.")
        last = frame
        count += 1
    assert first is not None and last is not None
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        codec = stream.codec_context.name
        fps = float(stream.average_rate or stream.base_rate or stream.guessed_rate)
    return VideoInfo(
        width=first.image.shape[1],
        height=first.image.shape[0],
        duration_seconds=last.timestamp + last.duration,
        fps=fps,
        frame_count=count,
        codec=codec,
        size_bytes=path.stat().st_size,
        timing="source_pts" if first.source_pts else "nominal_fps_fallback",
    )


class VideoWriter:
    def __init__(self, path: Path, info: VideoInfo):
        self.container = av.open(str(path), "w", format="mp4", options={"movflags": "+faststart"})
        self.stream = self.container.add_stream(
            "libx264", rate=Fraction(info.fps).limit_denominator(100000)
        )
        self.stream.width = info.width + info.width % 2
        self.stream.height = info.height + info.height % 2
        self.stream.pix_fmt = "yuv420p"
        self.stream.time_base = Fraction(1, 90000)
        self.stream.codec_context.time_base = Fraction(1, 90000)
        self.stream.options = {"preset": "veryfast", "crf": "23", "tune": "zerolatency", "bf": "0"}
        self.durations: dict[int, int] = {}
        self.closed = False

    def _mux(self, packets):
        for packet in packets:
            if packet.pts in self.durations:
                packet.duration = self.durations.pop(packet.pts)
            self.container.mux(packet)

    def write(self, image: np.ndarray, timestamp: float, duration: float):
        if image.shape[1] != self.stream.width or image.shape[0] != self.stream.height:
            image = cv2.copyMakeBorder(
                image,
                0,
                self.stream.height - image.shape[0],
                0,
                self.stream.width - image.shape[1],
                cv2.BORDER_CONSTANT,
            )
        frame = av.VideoFrame.from_ndarray(image, format="bgr24")
        frame.time_base = self.stream.codec_context.time_base
        frame.pts = round(timestamp / frame.time_base)
        self.durations[frame.pts] = max(1, round(duration / frame.time_base))
        self._mux(self.stream.encode(frame))

    def close(self):
        if not self.closed:
            try:
                self._mux(self.stream.encode(None))
            finally:
                self.container.close()
                self.closed = True

    def abort(self):
        if not self.closed:
            self.container.close()
            self.closed = True
