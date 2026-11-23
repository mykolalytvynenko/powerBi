import json
from base64 import b64encode
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

from app.catalog import Catalog
from app.config import Settings
from app.fake import FakeSource
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Вхід увімкнено, як у звичайному режимі; дані демонстраційні."""
    return Settings(tenant_id="t", client_id="c", client_secret="x", session_secret="test",
                    fake_data=True, image_cache_dir=tmp_path)


@pytest.fixture
def open_settings(settings) -> Settings:
    """AUTH_DISABLED=1: доступ без входу."""
    return replace(settings, auth_disabled=True)


def signed_in(client: TestClient, secret: str) -> TestClient:
    """Кладе в клієнт cookie сесії так само, як це робить SessionMiddleware."""
    payload = b64encode(json.dumps({"user": {"name": "Тест", "username": "test@vsisvoi.ua"}}).encode())
    client.cookies.set("mbviewer", TimestampSigner(secret).sign(payload).decode())
    return client


@pytest.fixture
def client(settings):
    return signed_in(TestClient(create_app(settings, FakeSource())), settings.session_secret)


def test_requires_login(settings):
    c = TestClient(create_app(settings, FakeSource()))
    r = c.get("/brands?store=*", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login?next=")
    assert c.get("/img/x/1/medium").status_code == 401
    assert c.get("/health").status_code == 200


def test_signed_in_user_sees_name_and_logout(client):
    r = client.get("/")
    assert r.status_code == 200 and "Тест" in r.text and "/logout" in r.text


def test_open_access_without_login(open_settings):
    c = TestClient(create_app(open_settings, FakeSource()))
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 200 and "Хрещатик 27" in r.text
    assert "/logout" not in r.text  # без входу немає ні імені, ні «Вийти»
    r = c.get("/brands?store=*", follow_redirects=False)
    assert r.status_code == 200
    cat = Catalog(open_settings, FakeSource())
    b = cat._batches()[0]
    photo = cat.photos(b.batch_id)[0]
    assert c.get(f"/img/{b.batch_id}/{photo.item_id}/medium").status_code == 200
    # /login нічого не питає і повертає на сторінку
    r = c.get("/login?next=/brands%3Fstore%3D*", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/brands?store=*"


def test_open_access_ignores_stale_session(open_settings):
    c = signed_in(TestClient(create_app(open_settings, FakeSource())), open_settings.session_secret)
    r = c.get("/")
    assert r.status_code == 200 and "Тест" not in r.text and "/logout" not in r.text


def test_open_redirect_blocked(open_settings):
    c = TestClient(create_app(open_settings, FakeSource()))
    r = c.get("/login?next=//evil.example", follow_redirects=False)
    assert r.headers["location"] == "/"


def test_stores_page(client):
    r = client.get("/")
    assert r.status_code == 200 and "Хрещатик 27" in r.text and "Всі магазини" in r.text


def test_unknown_store_404(client):
    assert client.get("/brands?store=Nope").status_code == 404


def test_store_flow(client, settings):
    cat = Catalog(settings, FakeSource())
    brands = cat.brands_in_store("Хрещатик 27")
    assert brands
    r = client.get("/brand", params={"store": "Хрещатик 27", "brand": brands[0].title})
    assert r.status_code == 200
    latest = cat.latest_by_department("Хрещатик 27", brands[0].title)
    assert latest and all(b.store == "Хрещатик 27" for b in latest)
    b = latest[0]
    r = client.get(f"/batch/{b.batch_id}", params={"store": "Хрещатик 27"})
    assert r.status_code == 200 and "Попередні викладки" in r.text
    photo = cat.photos(b.batch_id)[0]
    r = client.get(f"/photo/{b.batch_id}/{photo.item_id}", params={"store": "Хрещатик 27"})
    assert r.status_code == 200
    img = client.get(f"/img/{b.batch_id}/{photo.item_id}/medium")
    assert img.status_code == 200 and img.headers["content-type"].startswith("image/")
    # кеш на диску
    assert (settings.image_cache_dir / "medium" / photo.item_id).exists()


def test_latest_is_newest_and_ordered(settings):
    cat = Catalog(settings, FakeSource())
    for store in [None, "Хрещатик 27"]:
        for brand in cat.brands_in_store(store):
            latest = cat.latest_by_department(store, brand.title)
            for b in latest:
                hist = cat.history(store, brand.title, b.department)
                assert hist[0] == b
            depts = [b.department for b in latest]
            assert depts == [d for d in cat.departments() if d in depts]


def test_all_stores_has_more_brands_or_equal(settings):
    cat = Catalog(settings, FakeSource())
    all_b = {b.title for b in cat.brands_in_store(None)}
    for s in cat.stores():
        assert {b.title for b in cat.brands_in_store(s.title)} <= all_b


def test_hidden_statuses(settings):
    cat = Catalog(settings, FakeSource())
    assert cat.batch("MB-ERR") is None


def test_image_must_belong_to_batch(client, settings):
    cat = Catalog(settings, FakeSource())
    b1, b2 = cat._batches()[0], cat._batches()[1]
    foreign = cat.photos(b2.batch_id)[0].item_id
    assert client.get(f"/img/{b1.batch_id}/{foreign}/large").status_code == 404
    assert client.get(f"/img/{b1.batch_id}/{foreign}/huge").status_code == 404


def test_batch_wrong_store_404(client, settings):
    cat = Catalog(settings, FakeSource())
    b = next(x for x in cat._batches() if x.store != "Хрещатик 27")
    assert client.get(f"/batch/{b.batch_id}", params={"store": "Хрещатик 27"}).status_code == 404
    assert client.get(f"/batch/{b.batch_id}", params={"store": "*"}).status_code == 200
