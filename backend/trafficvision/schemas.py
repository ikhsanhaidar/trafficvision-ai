from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

VehicleClass = Literal["car", "motorcycle", "bus", "truck"]


def _orientation(a, b, c):
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)


def _segments_touch(a, b, c, d):
    def on_segment(p, q, r):
        return (
            abs(_orientation(p, q, r)) < 1e-10
            and min(p.x, q.x) <= r.x <= max(p.x, q.x)
            and min(p.y, q.y) <= r.y <= max(p.y, q.y)
        )

    if any((on_segment(a, b, c), on_segment(a, b, d), on_segment(c, d, a), on_segment(c, d, b))):
        return True
    return (
        _orientation(a, b, c) * _orientation(a, b, d) < 0
        and _orientation(c, d, a) * _orientation(c, d, b) < 0
    )


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class CountLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    start: Point
    end: Point

    @model_validator(mode="after")
    def nonzero(self):
        if (self.start.x - self.end.x) ** 2 + (self.start.y - self.end.y) ** 2 < 0.0001:
            raise ValueError("Counting line must have nonzero length (at least 1% of frame).")
        return self


class AnalysisConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classes: list[VehicleClass] = Field(
        default_factory=lambda: ["car", "motorcycle", "bus", "truck"], min_length=1
    )
    confidence: float = Field(default=0.25, ge=0.1, le=0.95)
    image_size: Literal[320, 480, 640, 960, 1280] = 640
    device: Literal["cpu", "cuda:0"] = "cpu"
    roi: list[Point] = Field(default_factory=list, max_length=30)
    lines: list[CountLine] = Field(min_length=1, max_length=8)
    hysteresis: float = Field(default=0.008, ge=0.001, le=0.1)
    min_track_age: int = Field(default=3, ge=2, le=60)
    max_track_gap: int = Field(default=30, ge=1, le=300)

    @model_validator(mode="after")
    def geometry(self):
        if len(set(self.classes)) != len(self.classes):
            raise ValueError("Selected classes must be unique.")
        if len({line.id for line in self.lines}) != len(self.lines):
            raise ValueError("Line IDs must be unique.")
        if self.roi and len(self.roi) < 3:
            raise ValueError("ROI requires at least three points.")
        if self.roi:
            points = self.roi
            if len({(p.x, p.y) for p in points}) != len(points):
                raise ValueError("ROI cannot have duplicate vertices.")
            edges = list(zip(points, points[1:] + points[:1]))
            for i, (a, b) in enumerate(edges):
                for j in range(i + 1, len(edges)):
                    if j == i + 1 or (i == 0 and j == len(edges) - 1):
                        continue
                    if _segments_touch(a, b, *edges[j]):
                        raise ValueError("ROI polygon must not intersect itself.")
            area = (
                abs(sum(p.x * q.y - q.x * p.y for p, q in zip(points, points[1:] + points[:1]))) / 2
            )
            if area < 0.0001:
                raise ValueError("ROI polygon must enclose a nonzero area.")
        return self


class TrackObservation(BaseModel):
    track_id: int
    class_name: VehicleClass
    confidence: float
    bbox: tuple[float, float, float, float]


class CrossingEvent(BaseModel):
    run_id: str
    track_id: int
    class_name: VehicleClass
    line_id: str
    direction: Literal["A_to_B", "B_to_A"]
    timestamp_video: float


class VideoInfo(BaseModel):
    width: int
    height: int
    duration_seconds: float
    fps: float
    frame_count: int | None
    codec: str
    size_bytes: int
    timing: str = "source_pts"
