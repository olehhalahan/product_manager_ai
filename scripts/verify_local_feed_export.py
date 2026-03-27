#!/usr/bin/env python3
"""
Smoke tests: health, homepage, dev session, batch + merchant CSV export shape.

OAuth must be disabled for /auth/dev — this script clears GOOGLE_* before importing the app.

Usage (from repo root):
  python scripts/verify_local_feed_export.py

  # Against already running server (must allow dev auth):
  python scripts/verify_local_feed_export.py --http http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# SESSION_SECRET required for SessionMiddleware
if not os.getenv("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "local-test-session-secret-32chars!!"


def _strip_oauth_for_dev_auth() -> None:
    """app.main load_dotenv() may re-set GOOGLE_* from .env — clear again before /auth/dev."""
    for k in (
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "APPLE_CLIENT_ID",
        "DEPLOY_URL",
    ):
        os.environ.pop(k, None)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def run_testclient_tests() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    _strip_oauth_for_dev_auth()

    client = TestClient(app)

    r = client.get("/health")
    _assert(r.status_code == 200, f"/health {r.status_code}")
    _assert(r.json().get("status") == "ok", "/health JSON")

    r = client.get("/")
    _assert(r.status_code == 200, f"/ homepage {r.status_code}")

    r = client.get("/auth/dev?next=/upload", follow_redirects=True)
    _assert(r.status_code == 200, "dev login redirect chain")

    csv_body = (
        "id,title,description,link,image_link,price,currency\r\n"
        'sku-1,"BAD ALL CAPS TITLE","short",'
        '"https://example.com/p/sku-1","https://example.com/img/sku-1.jpg","29.99","USD"\r\n'
    ).encode("utf-8")

    files = {"file": ("test.csv", csv_body, "text/csv")}
    r = client.post(
        "/batches",
        files=files,
        data={"mode": "optimize"},
    )
    _assert(r.status_code == 200, f"POST /batches {r.status_code} {r.text[:500]}")
    data = r.json()
    bid = data.get("id")
    _assert(bool(bid), "batch id in response")

    r = client.get(f"/batches/{bid}/export")
    _assert(r.status_code == 200, f"export {r.status_code} {r.text[:200]}")
    _assert("text/csv" in (r.headers.get("content-type") or ""), "export content-type")
    disp = r.headers.get("content-disposition") or ""
    _assert("merchant_feed_" in disp, f"Content-Disposition: {disp}")

    buf = io.StringIO(r.text)
    reader = csv.DictReader(buf)
    rows = list(reader)
    _assert(len(rows) >= 1, "export at least one row")
    fn = reader.fieldnames or []
    for col in ("id", "title", "description", "link", "image_link", "price"):
        _assert(col in fn, f"missing column {col}, got {fn}")

    row = rows[0]
    _assert(row.get("id") == "sku-1", f"id {row.get('id')}")
    _assert(row.get("link", "").startswith("http"), "link")
    _assert(row.get("image_link", "").startswith("http"), "image_link")
    _assert("29.99" in (row.get("price") or ""), f"price {row.get('price')}")
    _assert(len((row.get("title") or "").strip()) > 0, "title empty")

    print("testclient: OK — /health, /, dev auth, POST /batches, GET export (GMC-shaped CSV)")


def run_http_tests(base: str) -> None:
    import http.cookiejar
    import json
    import uuid
    import urllib.request

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def open_req(req):
        return opener.open(req, timeout=120)

    r = open_req(urllib.request.Request(f"{base.rstrip('/')}/health", method="GET"))
    _assert(r.status == 200, "/health http")

    open_req(
        urllib.request.Request(
            f"{base.rstrip('/')}/auth/dev?next=/upload", method="GET"
        )
    )

    boundary = f"boundary{uuid.uuid4().hex}"
    csv_bytes = (
        "id,title,description,link,image_link,price,currency\r\n"
        'sku-h1,"T","d",'
        '"https://example.com/a","https://example.com/b.jpg","10","USD"\r\n'
    ).encode("utf-8")

    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="mode"\r\n\r\noptimize\r\n',
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="t.csv"\r\n'
            b"Content-Type: text/csv\r\n\r\n",
            csv_bytes,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )

    req = urllib.request.Request(
        f"{base.rstrip('/')}/batches",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    r = open_req(req)
    _assert(r.status == 200, "POST /batches")
    batch = json.loads(r.read().decode())
    bid = batch["id"]

    r = open_req(
        urllib.request.Request(
            f"{base.rstrip('/')}/batches/{bid}/export", method="GET"
        )
    )
    _assert(r.status == 200, "export")
    text = r.read().decode("utf-8")
    _assert("id,title,description" in text.split("\n")[0], "export header")

    print(f"http {base}: OK — health, dev auth, batch, merchant CSV export")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--http", metavar="URL")
    args = p.parse_args()

    if args.http:
        run_http_tests(args.http)
    else:
        run_testclient_tests()


if __name__ == "__main__":
    main()
