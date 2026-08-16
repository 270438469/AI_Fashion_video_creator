from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.db.database import Database
from app.services.secret_store import EncryptedSecretStore


CAPABILITIES = ("vision", "image", "video")
CAPABILITY_LABELS = {
    "vision": "视觉分析",
    "image": "换装图片",
    "video": "视频生成",
}


class RelaySelection(BaseModel):
    vision_provider_id: str = "kuaipao"
    vision_model: str = "gpt-5.6-sol"
    image_provider_id: str = "kuaipao"
    image_model: str = "gpt-image-2"
    video_provider_id: str = "kuaipao"
    video_model: str = "doubao-seedance-2.0-mini-720p"

    def provider_id(self, capability: str) -> str:
        return str(getattr(self, f"{capability}_provider_id"))

    def model(self, capability: str) -> str:
        return str(getattr(self, f"{capability}_model"))


@dataclass(frozen=True)
class RelayProfile:
    relay_id: str
    data: dict[str, Any]

    @property
    def label(self) -> str:
        return str(self.data["label"])

    @property
    def api_root(self) -> str:
        return str(self.data["api_root"]).rstrip("/")

    @property
    def openai_base_url(self) -> str:
        return str(self.data["openai_base_url"]).rstrip("/")

    @property
    def video(self) -> dict[str, str]:
        return dict(self.data["video"])


class RelayConfigStore:
    SETTINGS_KEY = "active_relay_config"

    def __init__(
        self,
        db: Database,
        profiles_path: Path,
        secrets: EncryptedSecretStore,
    ):
        self.db = db
        self.profiles_path = profiles_path
        self.secrets = secrets
        self._profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
        if not self._profiles:
            raise RuntimeError("No relay profiles configured")
        self._migrate_legacy_secrets()

    @property
    def relay_ids(self) -> list[str]:
        return list(self._profiles)

    def profile(self, provider_id: str) -> RelayProfile:
        try:
            return RelayProfile(provider_id, self._profiles[provider_id])
        except KeyError as exc:
            raise ValueError(f"Unsupported provider: {provider_id}") from exc

    def provider_ids_for(self, capability: str) -> list[str]:
        self._check_capability(capability)
        return [
            provider_id
            for provider_id, data in self._profiles.items()
            if data.get("models", {}).get(capability)
        ]

    def models_for(self, provider_id: str, capability: str) -> list[str]:
        self._check_capability(capability)
        models = self.profile(provider_id).data.get("models", {}).get(capability, [])
        if not models:
            raise ValueError(f"Provider {provider_id!r} does not support {capability}")
        return [str(model) for model in models]

    def default_model_for(self, provider_id: str, capability: str) -> str:
        self.models_for(provider_id, capability)
        return str(self.profile(provider_id).data["defaults"][capability])

    def base_url_for(self, provider_id: str, capability: str) -> str:
        profile = self.profile(provider_id)
        return profile.api_root if capability == "video" else profile.openai_base_url

    def selection(self) -> RelaySelection:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?", (self.SETTINGS_KEY,)
            ).fetchone()
        if row is None:
            return self._default_selection()
        try:
            raw = json.loads(row["value"])
            selection = self._selection_from_raw(raw)
            return self.validate(selection)
        except (ValueError, TypeError, json.JSONDecodeError):
            return self._repair_selection(locals().get("selection"))

    def validate(self, selection: RelaySelection) -> RelaySelection:
        for capability in CAPABILITIES:
            provider_id = selection.provider_id(capability)
            model = selection.model(capability)
            allowed = self.models_for(provider_id, capability)
            if model not in allowed:
                raise ValueError(
                    f"Model {model!r} is not preconfigured for "
                    f"{provider_id}/{capability}"
                )
        return selection

    def save(self, selection: RelaySelection) -> RelaySelection:
        selection = self.validate(selection)
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO settings(key,value) VALUES(?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (self.SETTINGS_KEY, selection.model_dump_json()),
            )
        return selection

    @staticmethod
    def secret_key(capability: str, provider_id: str) -> str:
        return f"relay:{capability}:{provider_id}:api_key"

    @staticmethod
    def legacy_secret_key(provider_id: str) -> str:
        return f"relay:{provider_id}:api_key"

    def api_key(self, capability: str, provider_id: str) -> str | None:
        self.models_for(provider_id, capability)
        return self.secrets.get(self.secret_key(capability, provider_id))

    def set_api_key(self, capability: str, provider_id: str, api_key: str) -> None:
        self.models_for(provider_id, capability)
        self.secrets.set(self.secret_key(capability, provider_id), api_key)

    def delete_api_key(self, capability: str, provider_id: str) -> bool:
        self.models_for(provider_id, capability)
        return self.secrets.delete(self.secret_key(capability, provider_id))

    def missing_capabilities(self, selection: RelaySelection | None = None) -> list[str]:
        selection = selection or self.selection()
        return [
            capability
            for capability in CAPABILITIES
            if not self.api_key(capability, selection.provider_id(capability))
        ]

    def public_catalog(self) -> dict[str, Any]:
        capabilities: dict[str, Any] = {}
        for capability in CAPABILITIES:
            providers = []
            for provider_id in self.provider_ids_for(capability):
                profile = self.profile(provider_id)
                secret_name = self.secret_key(capability, provider_id)
                providers.append(
                    {
                        "id": provider_id,
                        "label": profile.label,
                        "docs_url": profile.data["docs_url"],
                        "base_url": self.base_url_for(provider_id, capability),
                        "models": self.models_for(provider_id, capability),
                        "model_groups": profile.data.get("model_groups", {}).get(
                            capability, []
                        ),
                        "default_model": self.default_model_for(provider_id, capability),
                        "api_key_configured": self.secrets.has(secret_name),
                        "api_key_masked": self.secrets.masked(secret_name),
                    }
                )
            capabilities[capability] = {
                "label": CAPABILITY_LABELS[capability],
                "providers": providers,
            }
        return {"capabilities": capabilities}

    def public_status(self) -> dict[str, Any]:
        selection = self.selection()
        capabilities: dict[str, Any] = {}
        for capability in CAPABILITIES:
            provider_id = selection.provider_id(capability)
            profile = self.profile(provider_id)
            secret_name = self.secret_key(capability, provider_id)
            capabilities[capability] = {
                "provider_id": provider_id,
                "provider_label": profile.label,
                "base_url": self.base_url_for(provider_id, capability),
                "model": selection.model(capability),
                "api_key_configured": self.secrets.has(secret_name),
                "api_key_masked": self.secrets.masked(secret_name),
            }
        missing = self.missing_capabilities(selection)
        missing_labels = [
            f"{CAPABILITY_LABELS[capability]}（"
            f"{capabilities[capability]['provider_label']}）"
            for capability in missing
        ]
        return {
            **selection.model_dump(),
            "capabilities": capabilities,
            "capability_providers": {
                capability: selection.provider_id(capability)
                for capability in CAPABILITIES
            },
            "all_api_keys_configured": not missing,
            "missing_capabilities": missing,
            "missing_capability_labels": missing_labels,
            # Compatibility fields for consumers that still display one relay.
            "relay_id": selection.video_provider_id,
            "relay_label": capabilities["video"]["provider_label"],
            "base_url": capabilities["video"]["base_url"],
            "api_key_configured": capabilities["video"]["api_key_configured"],
            "api_key_masked": capabilities["video"]["api_key_masked"],
            "missing_provider_ids": [
                selection.provider_id(capability) for capability in missing
            ],
            "missing_provider_labels": missing_labels,
        }

    def _selection_from_raw(self, raw: dict[str, Any]) -> RelaySelection:
        if any(f"{capability}_provider_id" in raw for capability in CAPABILITIES):
            return RelaySelection.model_validate(raw)
        legacy_provider_id = str(raw.get("relay_id", "kuaipao"))
        legacy_profile = self.profile(legacy_provider_id).data
        legacy_routes = legacy_profile.get("capability_providers", {})
        values: dict[str, str] = {}
        for capability in CAPABILITIES:
            provider_id = str(legacy_routes.get(capability, legacy_provider_id))
            if provider_id not in self.provider_ids_for(capability):
                provider_id = self.provider_ids_for(capability)[0]
            model = str(
                raw.get(
                    f"{capability}_model",
                    self.default_model_for(provider_id, capability),
                )
            )
            values[f"{capability}_provider_id"] = provider_id
            values[f"{capability}_model"] = model
        return RelaySelection(**values)

    def _default_selection(self) -> RelaySelection:
        values: dict[str, str] = {}
        for capability in CAPABILITIES:
            provider_id = self.provider_ids_for(capability)[0]
            values[f"{capability}_provider_id"] = provider_id
            values[f"{capability}_model"] = self.default_model_for(
                provider_id, capability
            )
        return RelaySelection(**values)

    def _repair_selection(self, selection: RelaySelection | None) -> RelaySelection:
        if selection is None:
            return self._default_selection()
        values: dict[str, str] = {}
        for capability in CAPABILITIES:
            provider_id = selection.provider_id(capability)
            if provider_id not in self.provider_ids_for(capability):
                provider_id = self.provider_ids_for(capability)[0]
            model = selection.model(capability)
            if model not in self.models_for(provider_id, capability):
                model = self.default_model_for(provider_id, capability)
            values[f"{capability}_provider_id"] = provider_id
            values[f"{capability}_model"] = model
        return RelaySelection(**values)

    def _migrate_legacy_secrets(self) -> None:
        for provider_id in self.relay_ids:
            legacy_name = self.legacy_secret_key(provider_id)
            legacy_value = self.secrets.get(legacy_name)
            if not legacy_value:
                continue
            for capability in CAPABILITIES:
                if provider_id not in self.provider_ids_for(capability):
                    continue
                scoped_name = self.secret_key(capability, provider_id)
                if not self.secrets.has(scoped_name):
                    self.secrets.set(scoped_name, legacy_value)
            self.secrets.delete(legacy_name)

    @staticmethod
    def _check_capability(capability: str) -> None:
        if capability not in CAPABILITIES:
            raise ValueError(f"Unsupported capability: {capability}")
