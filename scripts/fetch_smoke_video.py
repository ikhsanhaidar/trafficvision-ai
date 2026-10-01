"""Fetch the pinned, licensed real-world traffic smoke fixture (standard library only)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE = {
    "title": "Changing lanes in Gothenburg ubt.ogv",
    "author": "Tomasz Sienicki (Wikimedia user Tsca)",
    "recorded_date": "2009-07-25",
    "source_page": "https://commons.wikimedia.org/wiki/File:Changing_lanes_in_Gothenburg_ubt.ogv",
    "source_revision": "https://commons.wikimedia.org/w/index.php?title=File:Changing_lanes_in_Gothenburg_ubt.ogv&oldid=1161093012",
    "download_url": "https://upload.wikimedia.org/wikipedia/commons/0/0a/Changing_lanes_in_Gothenburg_ubt.ogv",
    "license": "CC-BY-3.0",
    "license_url": "https://creativecommons.org/licenses/by/3.0/",
    "attribution": "Changing lanes in Gothenburg ubt.ogv, © 2009 Tomasz Sienicki, CC BY 3.0, via Wikimedia Commons.",
    "changes": "None: original file downloaded byte-for-byte. Analysis overlays are separate derived artifacts.",
    "synthetic": False,
    "ground_truth_available": False,
    "bytes": 9785538,
    "sha256": "55186644070ef8685332660374104acfa678ef258e9833c0f3920905bd68c919",
}
MAX_BYTES = 20 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path) -> None:
    if path.stat().st_size != SOURCE["bytes"] or sha256(path) != SOURCE["sha256"]:
        raise ValueError("Fixture size or SHA-256 differs from the reviewed original; refusing it.")


def fetch(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        verify(destination)
    else:
        temporary: Path | None = None
        try:
            request = Request(
                str(SOURCE["download_url"]),
                headers={"User-Agent": "TrafficVisionAI/0.1 licensed-smoke-fixture"},
            )
            with (
                urlopen(request, timeout=60) as response,
                tempfile.NamedTemporaryFile(
                    dir=destination.parent, prefix=".smoke-", suffix=".part", delete=False
                ) as output,
            ):
                temporary = Path(output.name)
                if not response.url.startswith("https://upload.wikimedia.org/"):
                    raise ValueError("Unexpected fixture redirect host.")
                size = 0
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("Fixture exceeds the 20 MiB download limit.")
                    output.write(chunk)
            verify(temporary)
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    manifest = destination.with_suffix(destination.suffix + ".source.json")
    manifest.write_text(json.dumps(SOURCE, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/smoke/gothenburg.ogv"))
    args = parser.parse_args()
    destination = fetch(args.output)
    print(f"Verified {destination}: {SOURCE['bytes']} bytes, SHA-256 {SOURCE['sha256']}")
    print(SOURCE["attribution"])
    print("No ground truth is supplied; a smoke run does not establish model accuracy.")


if __name__ == "__main__":
    main()
