"""Налаштування застосунку зі змінних середовища."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    base_url: str = "http://localhost:8000"
    session_secret: str = ""
    sp_hostname: str = "vsisvoi.sharepoint.com"
    sp_site_path: str = "/sites/MerchandisingTest"
    list_batches: str = "MerchandisingBatches"
    list_photos: str = "MerchandisingPhotos"
    list_stores: str = "MerchandisingStores"
    list_brands: str = "MerchandisingBrands"
    list_departments: str = "MerchandisingDepartments"
    cache_ttl: int = 120
    image_cache_dir: Path = Path("cache/images")
    timezone: str = "Europe/Kyiv"
    fake_data: bool = False
    auth_disabled: bool = False
    visible_statuses: tuple[str, ...] = field(default=("Completed", "Corrected", "Partial"))

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}"

    @property
    def redirect_uri(self) -> str:
        return f"{self.base_url}/auth/callback"

    @property
    def secure_cookies(self) -> bool:
        return self.base_url.startswith("https://")


def load_settings() -> Settings:
    env = os.environ.get
    s = Settings(
        tenant_id=env("TENANT_ID", ""),
        client_id=env("CLIENT_ID", ""),
        client_secret=env("CLIENT_SECRET", ""),
        base_url=env("BASE_URL", "http://localhost:8000").rstrip("/"),
        session_secret=env("SESSION_SECRET", ""),
        sp_hostname=env("SP_HOSTNAME", "vsisvoi.sharepoint.com"),
        sp_site_path=env("SP_SITE_PATH", "/sites/MerchandisingTest"),
        cache_ttl=int(env("CACHE_TTL", "120")),
        image_cache_dir=Path(env("IMAGE_CACHE_DIR", "cache/images")),
        timezone=env("TIMEZONE", "Europe/Kyiv"),
        fake_data=_flag("FAKE_DATA"),
        auth_disabled=_flag("AUTH_DISABLED"),
    )
    problems = []
    if not s.session_secret:
        if s.auth_disabled:
            object.__setattr__(s, "session_secret", "dev-only-secret")
        else:
            problems.append("SESSION_SECRET")
    if not s.auth_disabled or not s.fake_data:
        for name, value in (("TENANT_ID", s.tenant_id), ("CLIENT_ID", s.client_id), ("CLIENT_SECRET", s.client_secret)):
            if not value:
                problems.append(name)
    if problems:
        raise RuntimeError("Не задано змінні середовища: " + ", ".join(sorted(set(problems))))
    return s
