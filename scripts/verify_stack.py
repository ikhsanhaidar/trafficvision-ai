"""Prepare isolated Compose verification credentials, or exercise its real HTTP workflow."""

import argparse
import json
import secrets
import time
from pathlib import Path


def prepare():
    from pwdlib import PasswordHash

    root = Path("artifacts/stack")
    root.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(24)
    values = {
        "POSTGRES_PASSWORD": secrets.token_hex(24),
        "TV_SECRET_KEY": secrets.token_hex(32),
        "TV_ADMIN_USERNAME": "admin",
        "TV_ADMIN_PASSWORD_HASH": PasswordHash.recommended().hash(password),
        "TV_ALLOWED_ORIGINS": '["http://localhost:18080","http://127.0.0.1:18080"]',
        "TV_COOKIE_SECURE": "false",
        "TV_LEASE_SECONDS": "120",
        "APP_PORT": "18080",
    }
    env = root / "verify.env"
    if env.exists():
        print("Verification environment already exists; preserving its credentials.")
        return
    env.write_text(
        "\n".join(f"{key}='{value}'" for key, value in values.items()) + "\n", encoding="utf-8"
    )
    (root / "credentials.json").write_text(
        json.dumps({"username": "admin", "password": password}), encoding="utf-8"
    )
    lines = ["services:"]
    for service in ("api", "worker", "migrate", "scheduler", "recovery"):
        lines.extend(
            [f"  {service}:", "    env_file: !override", "      - ./artifacts/stack/verify.env"]
        )
    lines.extend(
        [
            "  db:",
            "    ports:",
            '      - "127.0.0.1:15432:5432"',
            "  redis:",
            "    ports:",
            '      - "127.0.0.1:16379:6379"',
        ]
    )
    (root / "override.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        "Prepared private verification environment under artifacts/stack; no credentials printed."
    )


def verify(base_url: str, timeout: int):
    import httpx

    credentials = json.loads(Path("artifacts/stack/credentials.json").read_text(encoding="utf-8"))
    output = Path("artifacts/stack")
    with httpx.Client(base_url=base_url, headers={"Origin": base_url}, timeout=180) as client:
        assert client.get("/api/auth/me").status_code == 401
        response = client.post("/api/auth/login", json=credentials)
        response.raise_for_status()
        assert client.get("/api/auth/me").status_code == 200
        source = Path("data/smoke/gothenburg.ogv")
        with source.open("rb") as stream:
            response = client.post(
                "/api/videos", files={"file": (source.name, stream, "video/ogg")}
            )
        response.raise_for_status()
        uploaded = response.json()
        assert client.get(f"/api/videos/{uploaded['id']}/preview").status_code == 200
        config = json.loads(Path("examples/analysis.json").read_text(encoding="utf-8"))
        response = client.post(
            "/api/jobs", json={"video_id": uploaded["id"], "configuration": config}
        )
        response.raise_for_status()
        job_id = response.json()["id"]
        print(f"Started real stack analysis {job_id}", flush=True)
        started = time.monotonic()
        last_status = None
        while time.monotonic() - started < timeout:
            job = client.get(f"/api/jobs/{job_id}").raise_for_status().json()
            status = (job["status"], int(job["progress"] * 10) * 10)
            if status != last_status:
                print(f"{status[0]} {status[1]}%", flush=True)
                last_status = status
            if job["status"] in ("succeeded", "failed", "canceled"):
                break
            time.sleep(2)
        assert job["status"] == "succeeded", job
        summary = client.get(f"/api/jobs/{job_id}/result").raise_for_status().json()
        events = client.get(f"/api/jobs/{job_id}/events").raise_for_status().json()
        for format_ in ("json", "csv"):
            content = (
                client.get(f"/api/jobs/{job_id}/export", params={"format": format_})
                .raise_for_status()
                .content
            )
            (output / f"export.{format_}").write_bytes(content)
        exported = json.loads((output / "export.json").read_text(encoding="utf-8"))
        assert len(exported["events"]) == summary["crossing_total"] == events["total"]
        video = client.get(f"/api/jobs/{job_id}/video", headers={"Range": "bytes=0-1023"})
        assert video.status_code == 206 and len(video.content) == 1024
        (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        client.post("/api/auth/logout").raise_for_status()
        assert client.get(f"/api/jobs/{job_id}/video").status_code == 401
        assert client.get(f"/api/jobs/{job_id}/export?format=json").status_code == 401
        report = {
            "status": "passed",
            "job_id": job_id,
            "real_model": True,
            "real_video": True,
            "database": "PostgreSQL",
            "queue": "Redis/Celery",
            "crossings": summary["crossing_total"],
            "processing_seconds": summary["processing_seconds"],
            "throughput_fps": summary["throughput_fps"],
            "accuracy_evaluated": False,
        }
        (output / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--base-url", default="http://localhost:18080")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    prepare() if args.prepare else verify(args.base_url, args.timeout)


if __name__ == "__main__":
    main()
