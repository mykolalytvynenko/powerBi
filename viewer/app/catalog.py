"""Логіка перегляду: та сама, що в Power Apps «Зразки викладок».

магазин → бренди магазину → остання викладка кожного відділу → фото пакета (+ історія 10 пакетів).
Режим «Всі магазини» (store=None) прибирає фільтр за магазином.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .config import Settings
from .graph import DataSource

BATCH_FIELDS = (
    "Title", "Store", "Brand", "Department", "Collection", "MessageCreated",
    "ProcessedPhotos", "ChangeType", "Status",
)
PHOTO_FIELDS = ("BatchID", "PhotoIndex", "LinkStatus", "FileLeafRef")


@dataclass(frozen=True)
class Store:
    title: str
    city: str
    aliases: str


@dataclass(frozen=True)
class Brand:
    title: str
    aliases: str

    @property
    def letter(self) -> str:
        return self.title[:1].upper()

    @property
    def script(self) -> str:
        first = self.title[:1]
        return "Latin" if first.isascii() and first.isalnum() else "Cyr"


@dataclass(frozen=True)
class Batch:
    batch_id: str
    store: str
    brand: str
    department: str
    collection: str
    created: datetime | None
    photos: int
    change_type: str
    status: str


@dataclass(frozen=True)
class Photo:
    item_id: str
    index: int
    name: str


def _text(v: Any) -> str:
    """Choice/текст з Graph приходить рядком; про всяк випадок обробляємо і словник/список."""
    if v is None:
        return ""
    if isinstance(v, dict):
        return str(v.get("Value") or v.get("LookupValue") or "")
    if isinstance(v, list):
        return ", ".join(_text(x) for x in v)
    return str(v).strip()


def _active(v: Any) -> bool:
    return v is None or v is True or str(v).lower() in {"true", "1", "yes"}


def _date(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _int(v: Any) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _odata_quote(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"


class _Ttl:
    """Простий кеш з терміном життя: значення перечитується не частіше ніж раз на ttl секунд."""

    def __init__(self, ttl: int):
        self.ttl = ttl
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str, load: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._data.get(key)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
        value = load()
        with self._lock:
            self._data[key] = (now, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class Catalog:
    def __init__(self, settings: Settings, source: DataSource):
        self.s = settings
        self.src = source
        self.cache = _Ttl(settings.cache_ttl)
        self.tz = ZoneInfo(settings.timezone)

    # --- довідники ---

    def stores(self) -> list[Store]:
        def load() -> list[Store]:
            rows = self.src.list_items(self.s.list_stores, ("Title", "City", "Aliases", "IsActive"))
            items = [
                Store(_text(r.get("Title")), _text(r.get("City")), _text(r.get("Aliases")))
                for r in rows
                if _active(r.get("IsActive")) and _text(r.get("Title"))
            ]
            return sorted(items, key=lambda x: x.title.casefold())

        return self.cache.get("stores", load)

    def _brand_directory(self) -> dict[str, Brand]:
        def load() -> dict[str, Brand]:
            rows = self.src.list_items(self.s.list_brands, ("Title", "Aliases", "IsActive"))
            return {
                _text(r["Title"]): Brand(_text(r["Title"]), _text(r.get("Aliases")))
                for r in rows
                if _active(r.get("IsActive")) and _text(r.get("Title"))
            }

        return self.cache.get("brands", load)

    def departments(self) -> list[str]:
        def load() -> list[str]:
            rows = self.src.list_items(self.s.list_departments, ("Title", "IsActive"))
            rows.sort(key=lambda r: _int(r.get("id")))  # порядок, як у списку
            return [_text(r["Title"]) for r in rows if _active(r.get("IsActive")) and _text(r.get("Title"))]

        return self.cache.get("departments", load)

    # --- пакети ---

    def _batches(self) -> list[Batch]:
        def load() -> list[Batch]:
            rows = self.src.list_items(self.s.list_batches, BATCH_FIELDS)
            out = []
            for r in rows:
                b = Batch(
                    batch_id=_text(r.get("Title")),
                    store=_text(r.get("Store")),
                    brand=_text(r.get("Brand")),
                    department=_text(r.get("Department")),
                    collection=_text(r.get("Collection")),
                    created=_date(r.get("MessageCreated")),
                    photos=_int(r.get("ProcessedPhotos")),
                    change_type=_text(r.get("ChangeType")),
                    status=_text(r.get("Status")),
                )
                if b.batch_id and b.status in self.s.visible_statuses:
                    out.append(b)
            out.sort(key=lambda b: b.created or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            return out

        return self.cache.get("batches", load)

    def _in_store(self, store: str | None) -> list[Batch]:
        batches = self._batches()
        return batches if store is None else [b for b in batches if b.store == store]

    def brands_in_store(self, store: str | None) -> list[Brand]:
        directory = self._brand_directory()
        names = {b.brand for b in self._in_store(store) if b.brand}
        brands = [directory.get(n, Brand(n, "")) for n in names]
        return sorted(brands, key=lambda x: x.title.casefold())

    def latest_by_department(self, store: str | None, brand: str) -> list[Batch]:
        """Найновіший пакет кожного активного відділу (пакети вже відсортовані від нових)."""
        latest: dict[str, Batch] = {}
        for b in self._in_store(store):
            if b.brand == brand and b.department not in latest:
                latest[b.department] = b
        order = self.departments()
        known = [latest[d] for d in order if d in latest]
        # відділи, яких уже немає в довіднику, показуємо в кінці, щоб фото не зникали
        rest = [b for d, b in latest.items() if d not in order]
        return known + rest

    def history(self, store: str | None, brand: str, department: str, limit: int = 10) -> list[Batch]:
        return [b for b in self._in_store(store) if b.brand == brand and b.department == department][:limit]

    def batch(self, batch_id: str) -> Batch | None:
        return next((b for b in self._batches() if b.batch_id == batch_id), None)

    def photos(self, batch_id: str) -> list[Photo]:
        def load() -> list[Photo]:
            rows = self.src.list_items(self.s.list_photos, PHOTO_FIELDS, f"fields/BatchID eq {_odata_quote(batch_id)}")
            items = [
                Photo(str(r["id"]), _int(r.get("PhotoIndex")), _text(r.get("FileLeafRef")))
                for r in rows
                if _text(r.get("BatchID")) == batch_id and _text(r.get("LinkStatus")) in ("", "Linked")
            ]
            return sorted(items, key=lambda p: (p.index, _int(p.item_id)))

        return self.cache.get(f"photos:{batch_id}", load)

    def photo_belongs(self, batch_id: str, item_id: str) -> bool:
        return any(p.item_id == item_id for p in self.photos(batch_id))

    def local(self, dt: datetime | None) -> str:
        return dt.astimezone(self.tz).strftime("%d.%m.%Y %H:%M") if dt else ""
