"""Private, generated storage paths. Uploaded names are display metadata only."""

import shutil
import uuid
from pathlib import Path


def canonical_id(value: str) -> str:
    parsed = str(uuid.UUID(value))
    if parsed != value:
        raise ValueError("Invalid identifier.")
    return parsed


def display_filename(value: str | None) -> str:
    name = (value or "video").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(char for char in name if char.isprintable()).strip()
    return (name or "video")[:240]


class Storage:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def initialize(self):
        for name in ("videos", "results"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def resolve(self, relative: str | Path) -> Path:
        target = (self.root / relative).resolve()
        if not target.is_relative_to(self.root) or target == self.root:
            raise ValueError("Storage path must remain inside the private storage root.")
        return target

    def video_dir(self, video_id: str) -> Path:
        return self.resolve(Path("videos") / canonical_id(video_id))

    def result_dir(self, job_id: str, attempt: int, token: str) -> Path:
        if attempt < 1:
            raise ValueError("Invalid attempt.")
        return self.resolve(
            Path("results") / canonical_id(job_id) / f"{attempt}-{canonical_id(token)}"
        )

    def delete(self, target: Path):
        checked = self.resolve(target)
        if checked.is_dir():
            shutil.rmtree(checked)
        elif checked.exists():
            checked.unlink()
