from pathlib import Path

from app.db.database import Database
from app.services.secret_store import EncryptedSecretStore


def test_api_key_is_encrypted_and_only_masked_value_is_exposed(tmp_path: Path):
    db = Database(tmp_path / "app.db")
    store = EncryptedSecretStore(db, tmp_path / ".secrets" / "master.key")
    secret = "sk-secret-1234"

    store.set("relay:kuaipao:api_key", secret)

    assert store.get("relay:kuaipao:api_key") == secret
    assert store.masked("relay:kuaipao:api_key").endswith("1234")
    assert secret.encode() not in (tmp_path / "app.db").read_bytes()
    assert secret.encode() not in (tmp_path / ".secrets" / "master.key").read_bytes()
    assert store.delete("relay:kuaipao:api_key") is True
    assert store.get("relay:kuaipao:api_key") is None

