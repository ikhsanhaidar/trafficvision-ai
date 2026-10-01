"""Count finite-line crossings from isolated, bounded active track trajectories.

A is the negative cross-product side of a directed line; B is positive.
The run-level deduplication and frozen-label records intentionally survive active
track eviction. They are compact, but grow with the number of counted tracks.
"""

from dataclasses import dataclass, field
from math import hypot, isfinite

from trafficvision.schemas import AnalysisConfig, CountLine, CrossingEvent, TrackObservation

Coordinate = tuple[float, float]
_EPSILON = 1e-10


def _cross(a: Coordinate, b: Coordinate, p: Coordinate) -> float:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _on_segment(a: Coordinate, b: Coordinate, p: Coordinate) -> bool:
    return (
        abs(_cross(a, b, p)) <= _EPSILON
        and min(a[0], b[0]) - _EPSILON <= p[0] <= max(a[0], b[0]) + _EPSILON
        and min(a[1], b[1]) - _EPSILON <= p[1] <= max(a[1], b[1]) + _EPSILON
    )


def _inside_polygon(point: Coordinate, polygon: list[Coordinate]) -> bool:
    """Ray casting with the polygon boundary included in the ROI."""
    if not polygon:
        return True
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if _on_segment(a, b, point):
            return True
        if (a[1] > point[1]) != (b[1] > point[1]):
            intersection_x = a[0] + (point[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if point[0] < intersection_x:
                inside = not inside
    return inside


@dataclass
class _LineState:
    stable_side: int = 0
    raw_side: int = 0
    zero_point: Coordinate | None = None
    zero_timestamp: float = 0.0
    # Latest actual side change, only when its intersection lies on the segment.
    candidate: tuple[int, float] | None = None


@dataclass
class _TrackState:
    last_frame: int
    age: int = 0
    previous_point: Coordinate | None = None
    previous_timestamp: float = 0.0
    scores: dict[str, float] = field(default_factory=dict)
    lines: dict[str, _LineState] = field(default_factory=dict)

    def reset_trajectory(self) -> None:
        self.age = 0
        self.previous_point = None
        self.lines.clear()


class CrossingCounter:
    """One instance per run; feed source frames in increasing frame order.

    Event time is interpolated between the source timestamps adjacent to the
    actual intersection. Confirmation may occur later, after leaving the
    hysteresis band. Track age is the number of observations in the current
    uninterrupted ROI visit. A frame gap greater than ``max_track_gap`` resets
    the active trajectory. A repeated frame never increases age or emits events.
    """

    def __init__(self, config: AnalysisConfig, run_id: str, width: int, height: int):
        if width <= 0 or height <= 0:
            raise ValueError("Frame width and height must be positive.")
        self.config = config.model_copy(deep=True)
        self.run_id = run_id
        self.width = width
        self.height = height
        self._polygon = [(p.x, p.y) for p in config.roi]
        self._tracks: dict[int, _TrackState] = {}
        self._counted: set[tuple[int, str, str]] = set()
        self._frozen_classes: dict[int, str] = {}
        self._last_frame: int | None = None

    def class_name(self, track_id: int) -> str:
        """Return the confidence-voted label, frozen after the first count."""
        if track_id in self._frozen_classes:
            return self._frozen_classes[track_id]
        state = self._tracks.get(track_id)
        if state is None or not state.scores:
            return "unknown"
        return max(state.scores, key=lambda label: state.scores[label])

    def update(
        self,
        observations: list[TrackObservation],
        timestamp_video: float,
        frame_index: int,
    ) -> list[CrossingEvent]:
        if self._last_frame is not None and frame_index < self._last_frame:
            raise ValueError("Frames must be processed in increasing order.")
        if not isfinite(timestamp_video):
            raise ValueError("Video timestamp must be finite.")
        if frame_index == self._last_frame:
            return []
        self._last_frame = frame_index
        self._tracks = {
            track_id: state
            for track_id, state in self._tracks.items()
            if frame_index - state.last_frame <= self.config.max_track_gap
        }
        events: list[CrossingEvent] = []
        seen: set[int] = set()
        for observation in observations:
            track_id = observation.track_id
            if track_id in seen or observation.class_name not in self.config.classes:
                continue
            seen.add(track_id)
            x1, _, x2, y2 = observation.bbox
            point = ((x1 + x2) / (2 * self.width), y2 / self.height)
            if not all(isfinite(value) for value in (*point, observation.confidence)):
                continue
            state = self._tracks.setdefault(track_id, _TrackState(last_frame=frame_index))
            state.last_frame = frame_index
            if track_id not in self._frozen_classes:
                label = observation.class_name
                state.scores[label] = state.scores.get(label, 0.0) + observation.confidence
            if not _inside_polygon(point, self._polygon):
                state.reset_trajectory()
                continue
            state.age += 1
            for line in self.config.lines:
                line_state = state.lines.setdefault(line.id, _LineState())
                crossing = self._advance_line(line, line_state, state, point, timestamp_video)
                if crossing is None or state.age < self.config.min_track_age:
                    continue
                direction, crossing_timestamp = crossing
                key = (track_id, line.id, direction)
                if key in self._counted:
                    continue
                label = self.class_name(track_id)
                self._counted.add(key)
                self._frozen_classes[track_id] = label
                # Votes are no longer needed once the label is frozen.
                state.scores.clear()
                events.append(
                    CrossingEvent(
                        run_id=self.run_id,
                        track_id=track_id,
                        class_name=label,
                        line_id=line.id,
                        direction=direction,
                        timestamp_video=crossing_timestamp,
                    )
                )
            state.previous_point = point
            state.previous_timestamp = timestamp_video
        return events

    def _advance_line(
        self,
        line: CountLine,
        state: _LineState,
        track: _TrackState,
        point: Coordinate,
        timestamp: float,
    ) -> tuple[str, float] | None:
        a, b = (line.start.x, line.start.y), (line.end.x, line.end.y)
        length = hypot(b[0] - a[0], b[1] - a[1])
        distance = _cross(a, b, point) / length
        raw_side = 1 if distance > _EPSILON else -1 if distance < -_EPSILON else 0

        if raw_side == 0:
            # Preserve the last arrival/departure point for paths that touch or
            # travel along the line; merely touching it is never a crossing.
            state.zero_point = point
            state.zero_timestamp = timestamp
        else:
            if state.raw_side and raw_side != state.raw_side and track.previous_point is not None:
                previous = track.previous_point
                if state.zero_point is not None:
                    intersection, crossing_time = state.zero_point, state.zero_timestamp
                else:
                    previous_distance = _cross(a, b, previous) / length
                    fraction = previous_distance / (previous_distance - distance)
                    intersection = (
                        previous[0] + fraction * (point[0] - previous[0]),
                        previous[1] + fraction * (point[1] - previous[1]),
                    )
                    crossing_time = track.previous_timestamp + fraction * (
                        timestamp - track.previous_timestamp
                    )
                state.candidate = (
                    (raw_side, crossing_time)
                    if _on_segment(a, b, intersection)
                    and _inside_polygon(intersection, self._polygon)
                    else None
                )
            state.raw_side = raw_side
            state.zero_point = None

        stable_side = (
            1
            if distance >= self.config.hysteresis
            else -1
            if distance <= -self.config.hysteresis
            else 0
        )
        if not stable_side:
            return None
        crossing = None
        if state.stable_side and stable_side != state.stable_side:
            if state.candidate is not None and state.candidate[0] == stable_side:
                direction = "A_to_B" if stable_side == 1 else "B_to_A"
                crossing = (direction, state.candidate[1])
        state.stable_side = stable_side
        state.candidate = None
        return crossing
