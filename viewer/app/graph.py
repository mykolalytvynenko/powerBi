"""Доступ до SharePoint через Microsoft Graph (app-only, Sites.Selected).

Застосунок тільки читає: списки через /lists/{name}/items, фото через driveItem.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Iterable, Protocol

import httpx
import msal

from .config import Settings

GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]

# Розміри зображень, які віддає застосунок.
#   medium   ~176 px, сітка фото
#   large    ~800 px, перегляд одного фото
#   original оригінальний файл
IMAGE_SIZES = ("medium", "large", "original")


class GraphError(RuntimeError):
    pass


class DataSource(Protocol):
    def list_items(self, list_name: str, fields: Iterable[str], filter_: str | None = None) -> list[dict[str, Any]]:
        """Повертає fields кожного рядка списку плюс ключ "id" (ID елемента)."""

    def image(self, list_name: str, item_id: str, size: str) -> tuple[bytes, str]:
        """Повертає (байти, content-type) зображення елемента бібліотеки."""


class GraphSource:
    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self._s = settings
        self._http = http or httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True)
        self._msal: msal.ConfidentialClientApplication | None = None  # створюється при першому запиті
        self._site_id: str | None = None
        self._lock = threading.Lock()

    # --- службове ---

    def _token(self) -> str:
        if self._msal is None:
            self._msal = msal.ConfidentialClientApplication(
                self._s.client_id, authority=self._s.authority, client_credential=self._s.client_secret
            )
        result = self._msal.acquire_token_for_client(scopes=GRAPH_SCOPE)
        if "access_token" not in result:
            raise GraphError(f"Не вдалося отримати токен: {result.get('error')}: {result.get('error_description')}")
        return result["access_token"]

    def _get(self, url: str, params: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> httpx.Response:
        h = {"Authorization": f"Bearer {self._token()}"}
        if headers:
            h.update(headers)
        resp = self._http.get(url, params=params, headers=h)
        if resp.status_code == 429 or resp.status_code >= 500:
            # одна повторна спроба після паузи, яку просить Graph
            time.sleep(min(float(resp.headers.get("Retry-After", "2")), 10.0))
            resp = self._http.get(url, params=params, headers=h)
        if resp.status_code >= 400:
            raise GraphError(f"Graph {resp.status_code} для {url}: {resp.text[:300]}")
        return resp

    def site_id(self) -> str:
        with self._lock:
            if self._site_id is None:
                data = self._get(f"{GRAPH}/sites/{self._s.sp_hostname}:{self._s.sp_site_path}").json()
                self._site_id = data["id"]
            return self._site_id

    # --- DataSource ---

    def list_items(self, list_name: str, fields: Iterable[str], filter_: str | None = None) -> list[dict[str, Any]]:
        params = {"expand": f"fields(select={','.join(fields)})", "$top": "999"}
        if filter_:
            params["$filter"] = filter_
        url: str | None = f"{GRAPH}/sites/{self.site_id()}/lists/{list_name}/items"
        # фільтр по полях працює тільки для індексованих колонок; заголовок прибирає відмову для решти
        headers = {"Prefer": "HonorNonIndexedQueriesWarningMayFailRandomly"}
        rows: list[dict[str, Any]] = []
        while url:
            data = self._get(url, params=params, headers=headers).json()
            for item in data.get("value", []):
                row = dict(item.get("fields", {}))
                row["id"] = item["id"]
                rows.append(row)
            url = data.get("@odata.nextLink")
            params = None  # nextLink уже містить параметри
        return rows

    def image(self, list_name: str, item_id: str, size: str) -> tuple[bytes, str]:
        if size not in IMAGE_SIZES:
            raise ValueError(size)
        base = f"{GRAPH}/sites/{self.site_id()}/lists/{list_name}/items/{item_id}/driveItem"
        url = f"{base}/content" if size == "original" else f"{base}/thumbnails/0/{size}/content"
        resp = self._get(url)
        return resp.content, resp.headers.get("Content-Type", "image/jpeg")
