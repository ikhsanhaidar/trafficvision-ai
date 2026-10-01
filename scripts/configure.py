"""Generate local secrets and an Argon2 password hash; never overwrite an existing env."""

import getpass
import secrets
from pathlib import Path

from pwdlib import PasswordHash


def main():
    target = Path(__file__).resolve().parents[1] / ".env"
    if target.exists():
        raise SystemExit(
            ".env already exists. Edit it deliberately; this script does not overwrite secrets."
        )
    password = getpass.getpass("Choose admin password (at least 12 characters): ")
    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters.")
    if password != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match.")
    db_password = secrets.token_hex(24)
    replacements = {
        "POSTGRES_PASSWORD": db_password,
        "TV_SECRET_KEY": secrets.token_hex(32),
        "TV_ADMIN_PASSWORD_HASH": PasswordHash.recommended().hash(password),
        "TV_DATABASE_URL": f"postgresql+psycopg://trafficvision:{db_password}@localhost:5432/trafficvision",
    }
    lines = []
    for line in target.with_name(".env.example").read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0]
        if key in replacements:
            # Single quotes stop Compose interpreting the '$' in Argon2 hashes.
            line = f"{key}='{replacements[key]}'"
        lines.append(line)
    with target.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    try:
        target.chmod(0o600)
    except OSError:
        pass
    print("Created .env. Admin username: admin. Keep the password and .env private.")


if __name__ == "__main__":
    main()
