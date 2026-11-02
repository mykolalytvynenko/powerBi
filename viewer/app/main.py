"""Веб-перегляд фото викладок (тільки читання)."""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from .auth import build_router
from .catalog import Catalog
from .config import Settings, load_settings
from .graph import IMAGE_SIZES, DataSource, GraphError, GraphSource

log = logging.getLogger("mbviewer")
HERE = Path(__file__).parent
ALL = "*"  # значення store для режиму «Всі магазини»
ALL_LABEL = "Всі магазини"
PUBLIC_PATHS = ("/login", "/auth/", "/logout", "/health", "/static/")
ITEM_ID = re.compile(r"^\d{1,12}$")


def create_app(settings: Settings | None = None, source: DataSource | None = None) -> FastAPI:
    settings = settings or load_settings()
    if source is None:
        if settings.fake_data:
            from .fake import FakeSource

            source = FakeSource()
        else:
            source = GraphSource(settings)
    catalog = Catalog(settings, source)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    image_dir = settings.image_cache_dir

    app = FastAPI(title="Зразки викладок", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.catalog = catalog

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        path = request.url.path
        if not path.startswith(PUBLIC_PATHS) and not request.session.get("user"):
            if path.startswith("/img/"):
                return Response(status_code=401)
            target = path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse("/login?" + urlencode({"next": target}), status_code=303)
        return await call_next(request)

    # SessionMiddleware додається після, щоб виконуватися раніше (зовнішній шар)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="mbviewer",
        max_age=12 * 3600,
        same_site="lax",
        https_only=settings.secure_cookies,
    )
    app.include_router(build_router(settings))
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    # --- допоміжне для шаблонів ---

    def store_arg(store: str | None) -> str | None:
        """'*' → None (усі магазини); невідомий магазин → 404."""
        if not store:
            raise HTTPException(404)
        if store == ALL:
            return None
        if store not in {s.title for s in catalog.stores()}:
            raise HTTPException(404, "Магазин не знайдено")
        return store

    def url(path: str, **params: str) -> str:
        clean = {k: v for k, v in params.items() if v is not None}
        return path + ("?" + urlencode(clean) if clean else "")

    def render(request: Request, name: str, **ctx) -> HTMLResponse:
        ctx.update(
            request=request,
            user=request.session.get("user"),
            url=url,
            q=lambda v: quote(v, safe=""),
            local=catalog.local,
            ALL=ALL,
            ALL_LABEL=ALL_LABEL,
        )
        return templates.TemplateResponse(request, name, ctx)

    # --- сторінки ---

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/auth/error", response_class=HTMLResponse)
    def auth_error(request: Request, msg: str = ""):
        return render(request, "error.html", title="Не вдалося увійти", message=msg[:500])

    @app.get("/", response_class=HTMLResponse)
    def stores(request: Request):
        return render(request, "stores.html", stores=catalog.stores())

    @app.get("/brands", response_class=HTMLResponse)
    def brands(request: Request, store: str = ""):
        s = store_arg(store)
        items = catalog.brands_in_store(s)
        return render(
            request, "brands.html", store=store, store_label=s or ALL_LABEL, brands=items,
            has_latin=any(b.script == "Latin" for b in items), has_cyr=any(b.script == "Cyr" for b in items),
        )

    @app.get("/brand", response_class=HTMLResponse)
    def brand(request: Request, store: str = "", brand: str = ""):
        s = store_arg(store)
        latest = catalog.latest_by_department(s, brand)
        covers = {}
        for b in latest:
            photos = catalog.photos(b.batch_id)
            covers[b.batch_id] = photos[0].item_id if photos else None
        return render(request, "brand.html", store=store, store_label=s or ALL_LABEL, brand=brand,
                      latest=latest, covers=covers)

    @app.get("/batch/{batch_id}", response_class=HTMLResponse)
    def batch(request: Request, batch_id: str, store: str = ""):
        s = store_arg(store)
        b = catalog.batch(batch_id)
        if b is None or (s is not None and b.store != s):
            raise HTTPException(404, "Викладку не знайдено")
        return render(request, "batch.html", store=store, store_label=s or ALL_LABEL, b=b,
                      photos=catalog.photos(batch_id), history=catalog.history(s, b.brand, b.department))

    @app.get("/photo/{batch_id}/{item_id}", response_class=HTMLResponse)
    def photo(request: Request, batch_id: str, item_id: str, store: str = ""):
        s = store_arg(store)
        b = catalog.batch(batch_id)
        photos = catalog.photos(batch_id)
        ids = [p.item_id for p in photos]
        if b is None or (s is not None and b.store != s) or item_id not in ids:
            raise HTTPException(404, "Фото не знайдено")
        i = ids.index(item_id)
        return render(request, "photo.html", store=store, b=b, item_id=item_id, pos=i + 1, total=len(ids),
                      prev_id=ids[i - 1] if i > 0 else None, next_id=ids[i + 1] if i + 1 < len(ids) else None)

    @app.get("/img/{batch_id}/{item_id}/{size}")
    def image(batch_id: str, item_id: str, size: str):
        if size not in IMAGE_SIZES or not ITEM_ID.match(item_id) or not catalog.photo_belongs(batch_id, item_id):
            raise HTTPException(404)
        headers = {"Cache-Control": "private, max-age=86400"}
        cached, ctype = _read_cache(image_dir, item_id, size)
        if cached is None:
            try:
                cached, ctype = source.image(settings.list_photos, item_id, size)
            except GraphError as e:
                log.warning("image %s/%s: %s", item_id, size, e)
                raise HTTPException(502, "Не вдалося завантажити фото")
            if size != "original":  # оригінали великі, не кешуємо на диску
                _write_cache(image_dir, item_id, size, cached, ctype)
        if size == "original":
            headers["Content-Disposition"] = f'inline; filename="photo-{item_id}.jpg"'
        return Response(cached, media_type=ctype, headers=headers)

    def error_page(request: Request, title: str, message: str, status: int) -> HTMLResponse:
        resp = render(request, "error.html", title=title, message=message)
        resp.status_code = status
        return resp

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/img/"):
            return Response(status_code=exc.status_code)
        if exc.status_code == 404:
            msg = exc.detail if exc.detail != "Not Found" else "Сторінку не знайдено"
            return error_page(request, "Не знайдено", msg, 404)
        return error_page(request, "Помилка", str(exc.detail), exc.status_code)

    @app.exception_handler(GraphError)
    async def graph_error(request: Request, exc: GraphError):
        log.error("graph: %s", exc)
        return error_page(request, "SharePoint недоступний",
                          "Спробуйте за хвилину. Якщо помилка не минає, повідомте адміністратора.", 502)

    return app


def _cache_paths(root: Path, item_id: str, size: str) -> tuple[Path, Path]:
    base = root / size / item_id
    return base, base.with_suffix(".type")


def _read_cache(root: Path, item_id: str, size: str) -> tuple[bytes | None, str]:
    data, ctype = _cache_paths(root, item_id, size)
    try:
        return data.read_bytes(), ctype.read_text().strip() or "image/jpeg"
    except OSError:
        return None, ""


def _write_cache(root: Path, item_id: str, size: str, content: bytes, ctype: str) -> None:
    data, type_file = _cache_paths(root, item_id, size)
    try:
        data.parent.mkdir(parents=True, exist_ok=True)
        type_file.write_text(ctype)
        fd, tmp = tempfile.mkstemp(dir=data.parent)
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp, data)
    except OSError as e:
        log.warning("cache write %s: %s", data, e)


def app_factory() -> FastAPI:  # для uvicorn --factory
    logging.basicConfig(level=logging.INFO)
    return create_app()
