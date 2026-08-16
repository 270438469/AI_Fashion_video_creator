from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.db.database import Database


class EncryptedSecretStore:
    """Small local encrypted secret store backed by the existing SQLite database."""

    def __init__(self, db: Database, key_path: Path):
        self.db = db
        self.key_path = key_path
        self._fernet = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if self.key_path.exists():
            return self.key_path.read_bytes().strip()
        key = Fernet.generate_key()
        self.key_path.write_bytes(key)
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return key

    def set(self, key: str, value: str) -> None:
        value = value.strip()
        if not value:
            raise ValueError("API Key cannot be empty")
        encrypted = self._fernet.encrypt(value.encode("utf-8"))
        now = datetime.now(timezone.utc).isoformat()
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO runtime_secrets(key,encrypted_value,updated_at) VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET encrypted_value=excluded.encrypted_value,
                updated_at=excluded.updated_at""",
                (key, encrypted, now),
            )

    def get(self, key: str) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT encrypted_value FROM runtime_secrets WHERE key=?", (key,)
            ).fetchone()
        if row is None:
            return None
        try:
            return self._fernet.decrypt(bytes(row["encrypted_value"])).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("Stored API Key cannot be decrypted with the local master key") from exc

    def require(self, key: str) -> str:
        value = self.get(key)
        if not value:
            raise RuntimeError("API_KEY_NOT_CONFIGURED")
        return value

    def delete(self, key: str) -> bool:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM runtime_secrets WHERE key=?", (key,))
        return cursor.rowcount > 0

    def has(self, key: str) -> bool:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM runtime_secrets WHERE key=?", (key,)
            ).fetchone()
        return row is not None

    def masked(self, key: str) -> str | None:
        value = self.get(key)
        if not value:
            return None
        tail = value[-4:] if len(value) >= 4 else "****"
        prefix = value[:3] if len(value) >= 7 else "key"
        return f"{prefix}-****{tail}"

