"""Демо-дані для розробки без доступу до SharePoint (FAKE_DATA=1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

STORES = [("Хрещатик 27", "Київ"), ("Lavina Mall", "Київ"), ("Forum Lviv", "Львів")]
BRANDS = ["CTRL", "Mango", "Reserved", "Сінсей"]
DEPTS = ["Жіночий", "Чоловічий", "Дитячий", "Унісекс"]
COLORS = ["#1f4e79", "#7a3e9d", "#2e7d32", "#c62828", "#ef6c00", "#00838f"]


class FakeSource:
    def __init__(self) -> None:
        now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
        self.batches: list[dict[str, Any]] = []
        self.photos: list[dict[str, Any]] = []
        photo_id = 100
        n = 0
        for si, (store, _) in enumerate(STORES):
            for bi, brand in enumerate(BRANDS):
                for di, dept in enumerate(DEPTS):
                    if (si + bi + di) % 3 == 2:
                        continue
                    for k in range(2):
                        n += 1
                        bid = f"MB-2026{n:04d}"
                        count = 2 + (n % 4)
                        self.batches.append({
                            "id": str(n), "Title": bid, "Store": store, "Brand": brand, "Department": dept,
                            "Collection": "AW26" if k else "AW27",
                            "MessageCreated": (now - timedelta(days=n + 7 * k)).isoformat().replace("+00:00", "Z"),
                            "ProcessedPhotos": count, "ChangeType": "Нова колекція" if k == 0 else "",
                            "Status": "Completed",
                        })
                        for i in range(count):
                            photo_id += 1
                            self.photos.append({
                                "id": str(photo_id), "BatchID": bid, "PhotoIndex": i + 1,
                                "LinkStatus": "Linked", "FileLeafRef": f"IMG_{photo_id}.jpg",
                            })
        self.batches.append({"id": "999", "Title": "MB-ERR", "Store": "Хрещатик 27", "Brand": "CTRL",
                             "Department": "Жіночий", "Status": "ParseError"})

    def list_items(self, list_name: str, fields: Iterable[str], filter_: str | None = None) -> list[dict[str, Any]]:
        if list_name.endswith("Stores"):
            return [{"id": str(i + 1), "Title": t, "City": c, "Aliases": "", "IsActive": True} for i, (t, c) in enumerate(STORES)]
        if list_name.endswith("Brands"):
            return [{"id": str(i + 1), "Title": t, "Aliases": "", "IsActive": True} for i, t in enumerate(BRANDS)]
        if list_name.endswith("Departments"):
            return [{"id": str(i + 1), "Title": t, "IsActive": True} for i, t in enumerate(DEPTS)]
        if list_name.endswith("Batches"):
            return [dict(b) for b in self.batches]
        if list_name.endswith("Photos"):
            rows = self.photos
            if filter_ and "eq '" in filter_:
                wanted = filter_.split("eq '", 1)[1].rstrip("'").replace("''", "'")
                rows = [p for p in rows if p["BatchID"] == wanted]
            return [dict(p) for p in rows]
        return []

    def image(self, list_name: str, item_id: str, size: str) -> tuple[bytes, str]:
        w, h = {"medium": (176, 234), "large": (600, 800)}.get(size, (1200, 1600))
        color = COLORS[int(item_id) % len(COLORS)]
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<rect width="100%" height="100%" fill="{color}"/>'
            f'<text x="50%" y="50%" fill="#fff" font-family="sans-serif" font-size="{w // 8}" '
            f'text-anchor="middle" dominant-baseline="middle">IMG {item_id}</text></svg>'
        )
        return svg.encode(), "image/svg+xml"
