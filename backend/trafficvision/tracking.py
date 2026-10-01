"""A fresh ByteTrack instance per run; no state is retained by the detector."""

from types import SimpleNamespace

from trafficvision.schemas import AnalysisConfig, TrackObservation


class ByteTrackAdapter:
    def __init__(self, config: AnalysisConfig, fps: float, names: dict[int, str]):
        from ultralytics.trackers.byte_tracker import BYTETracker

        self.names = names
        self.config = config
        self.tracker = BYTETracker(
            SimpleNamespace(
                track_high_thresh=config.confidence,
                track_low_thresh=0.1,
                new_track_thresh=config.confidence,
                track_buffer=config.max_track_gap,
                match_thresh=0.8,
                fuse_score=True,
            ),
            frame_rate=round(fps),
        )

    def update(self, boxes, image):
        tracks = self.tracker.update(boxes, image)
        return [
            TrackObservation(
                bbox=tuple(float(v) for v in row[:4]),
                track_id=int(row[4]),
                confidence=float(row[5]),
                class_name=self.names[int(row[6])],
            )
            for row in tracks
            if self.names[int(row[6])] in self.config.classes
        ]
