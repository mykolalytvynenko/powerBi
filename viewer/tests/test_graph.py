import httpx

from app.config import Settings
from app.graph import GraphSource


def make(handler):
    s = Settings(tenant_id="t", client_id="c", client_secret="x", session_secret="s")
    src = GraphSource(s, http=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))
    src._token = lambda: "TOKEN"
    return src


def test_list_items_paging_and_site():
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        assert req.headers["Authorization"] == "Bearer TOKEN"
        if req.url.path == "/v1.0/sites/vsisvoi.sharepoint.com:/sites/MerchandisingTest":
            return httpx.Response(200, json={"id": "SITE"})
        if "page2" in str(req.url):
            return httpx.Response(200, json={"value": [{"id": "2", "fields": {"Title": "B"}}]})
        assert req.url.params["$filter"] == "fields/BatchID eq 'x'"
        assert req.url.params["expand"] == "fields(select=Title)"
        return httpx.Response(200, json={
            "value": [{"id": "1", "fields": {"Title": "A"}}],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/sites/SITE/lists/L/items?page2",
        })

    rows = make(handler).list_items("L", ["Title"], "fields/BatchID eq 'x'")
    assert rows == [{"Title": "A", "id": "1"}, {"Title": "B", "id": "2"}]


def test_thumbnail_follows_redirect_without_token():
    def handler(req: httpx.Request):
        if req.url.path.endswith("MerchandisingTest"):
            return httpx.Response(200, json={"id": "SITE"})
        if req.url.host == "graph.microsoft.com":
            assert req.url.path.endswith("/items/42/driveItem/thumbnails/0/large/content")
            return httpx.Response(302, headers={"Location": "https://cdn.example/x.jpg"})
        assert "Authorization" not in req.headers  # токен не йде на сторонній хост
        return httpx.Response(200, content=b"JPEG", headers={"Content-Type": "image/jpeg"})

    data, ctype = make(handler).image("MerchandisingPhotos", "42", "large")
    assert data == b"JPEG" and ctype == "image/jpeg"
