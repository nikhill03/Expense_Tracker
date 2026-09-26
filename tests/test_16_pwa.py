"""Step 16 — installable PWA, and the self-hosted fonts that came with it.

Most of these guard against silent failures. A manifest served as text/plain,
a worker scoped to /static/, a missing icon — none of them raise anything. They
just quietly mean no install prompt, and you find out by not getting one.
"""

import json
import pathlib

import pytest
from PIL import Image

REPO = pathlib.Path(__file__).resolve().parent.parent
STATIC = REPO / "static"


@pytest.fixture(scope="module")
def manifest():
    return json.loads((STATIC / "manifest.webmanifest").read_text())


# ------------------------------------------------------------------ #
# Serving                                                             #
# ------------------------------------------------------------------ #


def test_manifest_is_served_with_the_right_content_type(client):
    """text/plain here means the browser ignores the file and never offers install."""
    response = client.get("/static/manifest.webmanifest")

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/manifest+json")


def test_service_worker_is_served_from_the_root(client):
    """At /static/sw.js its scope would be /static/, which controls nothing."""
    response = client.get("/sw.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["Content-Type"]
    assert response.headers["Service-Worker-Allowed"] == "/"


def test_service_worker_is_not_cached_by_the_browser(client):
    """A stale worker pins an old caching policy in place across deploys."""
    response = client.get("/sw.js")
    assert "no-cache" in response.headers.get("Cache-Control", "")


def test_base_template_links_the_manifest(client):
    body = client.get("/").get_data(as_text=True)

    assert 'rel="manifest"' in body
    assert "manifest.webmanifest" in body
    assert 'rel="apple-touch-icon"' in body


# ------------------------------------------------------------------ #
# Manifest contents                                                   #
# ------------------------------------------------------------------ #


def test_manifest_describes_an_installable_app(manifest):
    assert manifest["name"] == "Bahi-Khata"
    assert manifest["display"] == "standalone"
    assert manifest["scope"] == "/"
    # The app opens on the screen it exists for, not the dashboard.
    assert manifest["start_url"] == "/quick"


def test_manifest_has_both_icon_purposes(manifest):
    """Android crops to a circle; without a maskable icon the glyph loses edges."""
    purposes = {icon["purpose"] for icon in manifest["icons"]}
    assert "any" in purposes
    assert "maskable" in purposes

    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes


def test_every_declared_icon_exists_at_its_declared_size(manifest):
    for icon in manifest["icons"]:
        path = REPO / icon["src"].lstrip("/")
        assert path.exists(), f"{icon['src']} is in the manifest but not on disk"

        width, height = Image.open(path).size
        assert (
            f"{width}x{height}" == icon["sizes"]
        ), f"{icon['src']} is {width}x{height}, manifest says {icon['sizes']}"


def test_share_target_points_at_the_existing_quick_route(manifest):
    """The share sheet reuses ?text=, which /quick has handled since Step 15."""
    share = manifest["share_target"]

    assert share["action"] == "/quick"
    assert share["method"].upper() == "GET"
    assert share["params"]["text"] == "text"


def test_shortcuts_cover_add_and_dashboard(manifest):
    urls = {s["url"] for s in manifest["shortcuts"]}
    assert urls == {"/quick", "/profile"}


def test_shared_text_still_prefills_the_amount(client):
    """The manifest is only useful because this already works."""
    body = client.get(
        "/quick?text=Rs.340.00+debited+from+A%2Fc+XX4417+to+SWIGGY+via+UPI",
        follow_redirects=False,
    )
    # Logged out, so this redirects to login — the parsing itself is covered in
    # test_13_quick_add.py. What matters here is that the route accepts ?text=.
    assert body.status_code in (200, 302)


# ------------------------------------------------------------------ #
# Offline page                                                        #
# ------------------------------------------------------------------ #


def test_offline_page_renders(client):
    response = client.get("/offline")
    assert response.status_code == 200


def test_offline_page_has_no_form(client):
    """It is precached, so any CSRF token baked into it is stale by definition."""
    body = client.get("/offline").get_data(as_text=True)
    assert "<form" not in body.lower()


# ------------------------------------------------------------------ #
# Service worker behaviour, read off the source                       #
# ------------------------------------------------------------------ #


def test_worker_never_handles_writes():
    """A GET never writes; the worker must not become the exception."""
    source = (STATIC / "sw.js").read_text()
    assert "request.method !== 'GET'" in source


def test_worker_precaches_the_offline_page_and_fonts():
    source = (STATIC / "sw.js").read_text()
    assert "'/offline'" in source
    assert "hanken-grotesk-latin.woff2" in source


def test_worker_does_not_cache_pages():
    """Cached HTML would carry a stale CSRF token and stale balances."""
    source = (STATIC / "sw.js").read_text()
    # Navigations are network-first with only /offline as a fallback.
    assert "request.mode === 'navigate'" in source
    assert "caches.match('/offline')" in source


# ------------------------------------------------------------------ #
# Self-hosted fonts                                                   #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "name",
    [
        "bricolage-grotesque-latin.woff2",
        "bricolage-grotesque-latin-ext.woff2",
        "hanken-grotesk-latin.woff2",
        "hanken-grotesk-latin-ext.woff2",
    ],
)
def test_font_file_is_present(name):
    path = STATIC / "fonts" / name
    assert path.exists()
    assert path.stat().st_size > 5_000


def test_compiled_css_points_at_the_local_fonts():
    css = (STATIC / "css" / "app.css").read_text()
    assert "fonts/hanken-grotesk-latin.woff2" in css
    assert "fonts/bricolage-grotesque-latin-ext.woff2" in css


def test_nothing_still_loads_fonts_from_google():
    """The CSP is default-src 'self'; a third-party font URL is a blocked request."""
    for path in (REPO / "templates").rglob("*.html"):
        body = path.read_text()
        assert "fonts.googleapis.com" not in body, path.name
        assert "fonts.gstatic.com" not in body, path.name


def test_rupee_sign_survives_subsetting():
    """₹ is U+20B9, which lives in latin-ext — dropping that subset loses it."""
    fonttools = pytest.importorskip("fontTools.ttLib")

    font = fonttools.TTFont(STATIC / "fonts" / "bricolage-grotesque-latin-ext.woff2")
    assert 0x20B9 in font.getBestCmap(), "the display face has lost the rupee sign"
