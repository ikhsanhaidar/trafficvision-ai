import pytest
from pydantic import ValidationError
from trafficvision.counting import CrossingCounter
from trafficvision.schemas import AnalysisConfig, CountLine, Point, TrackObservation


def configuration(**overrides):
    values = {
        "lines": [CountLine(id="main", start=Point(x=0.2, y=0.5), end=Point(x=0.8, y=0.5))],
        "hysteresis": 0.02,
        "min_track_age": 2,
    }
    values.update(overrides)
    return AnalysisConfig(**values)


def observation(x, y, track_id=1, label="car", confidence=0.9):
    # Non-square source dimensions exercise independent x/y normalization.
    return TrackObservation(
        track_id=track_id,
        class_name=label,
        confidence=confidence,
        bbox=(x * 200 - 5, y * 100 - 20, x * 200 + 5, y * 100),
    )


def trajectory(points, config=None, counter=None, track_id=1, start=0):
    counter = counter or CrossingCounter(config or configuration(), "run-1", 200, 100)
    events = []
    for frame, (x, y) in enumerate(points, start=start):
        events.extend(counter.update([observation(x, y, track_id)], frame / 10, frame))
    return counter, events


@pytest.mark.parametrize(("ys", "direction"), [([0.3, 0.7], "A_to_B"), ([0.7, 0.3], "B_to_A")])
def test_counts_both_directions_at_source_intersection_time(ys, direction):
    _, events = trajectory([(0.5, y) for y in ys])
    assert len(events) == 1
    assert events[0].model_dump() == {
        "run_id": "run-1",
        "track_id": 1,
        "class_name": "car",
        "line_id": "main",
        "direction": direction,
        "timestamp_video": pytest.approx(0.05),
    }


@pytest.mark.parametrize("y", [0.3, 0.5, 0.7])
def test_stationary_objects_do_not_count(y):
    _, events = trajectory([(0.5, y)] * 40)
    assert events == []


def test_jitter_in_hysteresis_band_does_not_count():
    _, events = trajectory([(0.5, y) for y in [0.3] + [0.499, 0.501, 0.49, 0.51] * 20])
    assert events == []


def test_hysteresis_confirms_actual_segment_and_keeps_intersection_time():
    _, events = trajectory([(0.5, y) for y in [0.3, 0.49, 0.51, 0.7]])
    assert len(events) == 1
    assert events[0].timestamp_video == pytest.approx(0.15)


@pytest.mark.parametrize("x", [0.1, 0.9])
def test_crossing_infinite_extension_outside_endpoints_does_not_count(x):
    _, events = trajectory([(x, 0.3), (x, 0.7)])
    assert events == []


def test_bent_path_around_endpoint_never_uses_chord_across_deadband():
    # The chord from first to last point crosses the segment, but the real path
    # crosses the infinite line to its right, entirely inside the deadband.
    _, events = trajectory([(0.5, 0.3), (0.9, 0.49), (0.9, 0.51), (0.5, 0.7)])
    assert events == []


def test_later_outside_intersection_invalidates_earlier_candidate():
    _, events = trajectory(
        [(0.5, 0.3), (0.5, 0.51), (0.5, 0.49), (0.9, 0.49), (0.9, 0.51), (0.5, 0.7)]
    )
    assert events == []


def test_same_track_counts_once_per_line_per_direction():
    _, events = trajectory([(0.5, y) for y in [0.3, 0.7, 0.3, 0.7, 0.3]])
    assert [event.direction for event in events] == ["A_to_B", "B_to_A"]


def test_distinct_tracks_and_lines_count_independently():
    config = configuration(
        lines=[
            CountLine(id="first", start=Point(x=0.2, y=0.4), end=Point(x=0.8, y=0.4)),
            CountLine(id="second", start=Point(x=0.2, y=0.6), end=Point(x=0.8, y=0.6)),
        ]
    )
    counter = CrossingCounter(config, "run-1", 200, 100)
    counter.update([observation(0.5, 0.3, i) for i in [1, 2]], 0, 0)
    events = counter.update([observation(0.5, 0.7, i) for i in [1, 2]], 1, 1)
    assert {(event.track_id, event.line_id) for event in events} == {
        (1, "first"),
        (1, "second"),
        (2, "first"),
        (2, "second"),
    }


def test_counter_instances_isolate_trajectories_and_deduplication():
    first = CrossingCounter(configuration(), "first-run", 200, 100)
    second = CrossingCounter(configuration(), "second-run", 200, 100)
    first.update([observation(0.5, 0.3)], 0, 0)
    assert second.update([observation(0.5, 0.7)], 0, 0) == []
    assert first.update([observation(0.5, 0.7)], 0.1, 1)[0].run_id == "first-run"
    assert second.update([observation(0.5, 0.3)], 0.1, 1)[0].run_id == "second-run"


def test_confidence_weighted_class_is_frozen_after_first_crossing():
    counter = CrossingCounter(configuration(), "run-1", 200, 100)
    counter.update([observation(0.5, 0.3, label="truck", confidence=0.4)], 0, 0)
    counter.update([observation(0.5, 0.3, label="car", confidence=0.9)], 0.1, 1)
    events = counter.update([observation(0.5, 0.7, label="truck", confidence=0.4)], 0.2, 2)
    assert events[0].class_name == "car"
    counter.update([observation(0.5, 0.7, label="truck", confidence=0.99)], 0.3, 3)
    reverse = counter.update([observation(0.5, 0.3, label="truck", confidence=0.99)], 0.4, 4)
    assert reverse[0].class_name == "car"
    assert counter.class_name(1) == "car"


def test_minimum_age_suppresses_new_track_crossing():
    _, events = trajectory([(0.5, 0.3), (0.5, 0.7)], configuration(min_track_age=3))
    assert events == []


def test_gap_resets_trajectory_and_age():
    counter = CrossingCounter(configuration(max_track_gap=2), "run-1", 200, 100)
    counter.update([observation(0.5, 0.3)], 0, 0)
    assert counter.update([observation(0.5, 0.7)], 0.3, 3) == []
    events = counter.update([observation(0.5, 0.3)], 0.4, 4)
    assert [event.direction for event in events] == ["B_to_A"]


def test_inactive_tracks_are_evicted_but_dedup_and_frozen_class_survive():
    counter, events = trajectory([(0.5, 0.3), (0.5, 0.7)], configuration(max_track_gap=2))
    assert len(events) == 1
    counter.update([], 1, 10)
    assert not counter._tracks
    assert counter.class_name(1) == "car"
    counter.update([observation(0.5, 0.3, label="truck")], 1.1, 11)
    assert counter.update([observation(0.5, 0.7, label="truck")], 1.2, 12) == []
    reverse = counter.update([observation(0.5, 0.3, label="truck")], 1.3, 13)
    assert reverse[0].class_name == "car"


def test_roi_exit_resets_path_and_reentry_does_not_invent_crossing():
    config = configuration(
        roi=[Point(x=0.3, y=0.2), Point(x=0.7, y=0.2), Point(x=0.7, y=0.8), Point(x=0.3, y=0.8)]
    )
    counter, events = trajectory([(0.5, 0.3), (0.9, 0.7), (0.5, 0.7)], config)
    assert events == []
    _, events = trajectory([(0.5, 0.3)], counter=counter, start=3)
    assert [event.direction for event in events] == ["B_to_A"]


def test_roi_boundary_is_included():
    config = configuration(
        roi=[Point(x=0.3, y=0.2), Point(x=0.7, y=0.2), Point(x=0.7, y=0.8), Point(x=0.3, y=0.8)]
    )
    _, events = trajectory([(0.3, 0.3), (0.3, 0.7)], config)
    assert len(events) == 1


def test_touching_line_and_returning_to_same_side_does_not_count():
    _, events = trajectory([(0.5, y) for y in [0.3, 0.5, 0.5, 0.3]])
    assert events == []


def test_crossing_via_exact_line_point_counts_once():
    _, events = trajectory([(0.5, y) for y in [0.3, 0.5, 0.7]])
    assert len(events) == 1
    assert events[0].timestamp_video == pytest.approx(0.1)


def test_reversed_line_reverses_direction():
    config = configuration(
        lines=[CountLine(id="reverse", start=Point(x=0.8, y=0.5), end=Point(x=0.2, y=0.5))]
    )
    _, events = trajectory([(0.5, 0.3), (0.5, 0.7)], config)
    assert events[0].direction == "B_to_A"


def test_vertical_line_maps_side_with_non_square_frame_dimensions():
    config = configuration(
        lines=[CountLine(id="vertical", start=Point(x=0.5, y=0.2), end=Point(x=0.5, y=0.8))]
    )
    _, events = trajectory([(0.3, 0.5), (0.7, 0.5)], config)
    assert events[0].direction == "B_to_A"


def test_bottom_center_is_used_instead_of_box_center():
    _, events = trajectory([(0.5, 0.3), (0.5, 0.6)])
    assert len(events) == 1


def test_diagonal_line_hysteresis_uses_perpendicular_normalized_distance():
    config = configuration(
        lines=[CountLine(id="diagonal", start=Point(x=0.1, y=0.1), end=Point(x=0.9, y=0.9))]
    )
    counter, events = trajectory([(0.5, 0.3), (0.5, 0.52)], config)
    # Offset 0.02 in y is only 0.014 perpendicular to a 45-degree line.
    assert events == []
    events = counter.update([observation(0.5, 0.54)], 0.2, 2)
    assert len(events) == 1


def test_crossing_point_outside_concave_roi_does_not_count():
    config = configuration(
        roi=[
            Point(x=0.1, y=0.1),
            Point(x=0.9, y=0.1),
            Point(x=0.9, y=0.9),
            Point(x=0.6, y=0.9),
            Point(x=0.6, y=0.3),
            Point(x=0.4, y=0.3),
            Point(x=0.4, y=0.9),
            Point(x=0.1, y=0.9),
        ]
    )
    # Both observations are inside the inverted U, but their crossing is in its gap.
    _, events = trajectory([(0.3, 0.3), (0.7, 0.7)], config)
    assert events == []


def test_self_intersecting_roi_with_nonzero_area_is_rejected():
    with pytest.raises(ValidationError, match="intersect"):
        configuration(
            roi=[Point(x=0.1, y=0.1), Point(x=0.9, y=0.9), Point(x=0.1, y=0.8), Point(x=0.8, y=0.1)]
        )


def test_duplicate_observation_and_frame_do_not_advance_track_age():
    counter = CrossingCounter(configuration(min_track_age=3), "run-1", 200, 100)
    point = observation(0.5, 0.3)
    counter.update([point, point], 0, 0)
    counter.update([point], 0, 0)
    assert counter.update([observation(0.5, 0.7)], 0.1, 1) == []


def test_nonmonotonic_frame_sequence_is_rejected():
    counter = CrossingCounter(configuration(), "run-1", 200, 100)
    counter.update([], 0.2, 2)
    with pytest.raises(ValueError, match="increasing order"):
        counter.update([], 0.1, 1)
