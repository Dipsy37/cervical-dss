"""Progressive Web App files: the app must be installable and must never cache API data."""


def test_manifest_is_served(client):
    r = client.get("/manifest.json")
    assert r.status_code == 200
    m = r.json()
    assert m["display"] == "standalone"
    assert m["start_url"] == "/index.html"
    sizes = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= sizes          # minimum for Chrome's install prompt


def test_icons_exist(client):
    for path in ["/icons/icon-192.png", "/icons/icon-512.png", "/icons/icon-maskable-512.png",
                 "/icons/apple-touch-icon.png", "/icons/favicon-32.png"]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"] == "image/png"


def test_service_worker_skips_api(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert 'url.pathname.startsWith("/api/")' in r.text   # patient data is never cached


def test_service_worker_fetches_fresh_code_first(client):
    """After an update, phones must load the new pages and JavaScript, not an old saved copy."""
    sw = client.get("/sw.js").text
    assert 'req.mode === "navigate" || /\\.(js|css)$/.test(url.pathname)' in sw
    assert sw.index("fetch(req)") < sw.index("caches.match(req, { ignoreSearch: true })")


def test_offline_page_and_pages_link_manifest(client):
    assert client.get("/offline.html").status_code == 200
    for page in ["index.html", "chw.html", "assess.html", "result.html", "history.html",
                 "dashboard.html", "admin.html", "admin-assessments.html", "change-password.html"]:
        html = client.get(f"/{page}").text
        assert 'rel="manifest"' in html and "js/pwa.js" in html, page


def test_iphone_support(client):
    for page in ["index.html", "chw.html", "assess.html", "result.html", "history.html",
                 "dashboard.html", "admin.html", "admin-assessments.html", "change-password.html",
                 "offline.html"]:
        html = client.get(f"/{page}").text
        assert 'name="apple-mobile-web-app-title" content="CC Risk"' in html, page
        assert 'rel="apple-touch-icon"' in html or page == "offline.html", page
    assert 'id="iosInstallHint"' in client.get("/index.html").text
    assert "iosInstallHint" in client.get("/js/pwa.js").text
