"""The plugin store, as seen from Edge Dash.

The store is the one DECK//SWITCH uses (https://streamdeckstore.labratox.de).
Edge Dash widgets are filed there under `app=edgedash`, so every catalog
request carries that parameter; without it the store answers for the deck
software.

Signing in uses GitHub's device flow, the same as the deck software: the
store hands out a code, the user enters it on github.com, and the token that
comes back is kept in a file only this user can read. It is never part of the
config, which the settings window reads and writes as a whole.
"""

from __future__ import annotations

import contextlib
import io
import os
import zipfile
from pathlib import Path
from typing import Any

import httpx

from .plugin_layout import APP

STORE_URL = os.environ.get("EDGE_STORE_URL", "https://streamdeckstore.labratox.de").rstrip("/")

TIMEOUT_S = 15.0

#: Not packed when a widget folder is submitted: caches, editor files, history.
SKIPPED_PARTS = {"__pycache__", ".git", ".mypy_cache", ".ruff_cache", ".pytest_cache", "node_modules"}


class StoreError(Exception):
    """The store said no, or could not be reached. `status` is the HTTP code."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def token_file() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config_home) / "edge-dashboard" / "store-token"


def read_token() -> str:
    try:
        return token_file().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_token(token: str) -> None:
    path = token_file()
    if not token:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Created with its mode before anything is written: a `write_text`
    # followed by `chmod` leaves a moment in which the token is readable by
    # everyone on the machine.
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(token, encoding="utf-8")


def _detail(response: httpx.Response) -> str:
    """The store's own explanation, which is written for people."""
    try:
        body = response.json()
    except ValueError:
        body = None
    # A proxy in front of the store may answer with any JSON, not only an
    # object; only an object can carry the explanation.
    if isinstance(body, dict):
        text = body.get("detail") or body.get("message")
        if isinstance(text, str) and text:
            return text
    if response.status_code == 401:
        return "not signed in to the store"
    return f"store answered HTTP {response.status_code}"


async def _request(
    method: str,
    path: str,
    *,
    auth: bool = False,
    auth_if_present: bool = False,
    params: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Any:
    """One request to the store, answered as JSON.

    `auth` requires a sign-in. `auth_if_present` sends it only when there is
    one: anyone may read a rating, but whoever is signed in should get their
    own vote back with it.
    """
    headers = {"Accept": "application/json", "User-Agent": "EdgeDash"}
    token = read_token()
    if auth and not token:
        raise StoreError("not signed in to the store", status=401)
    if token and (auth or auth_if_present):
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            response = await client.request(
                method, f"{STORE_URL}{path}", headers=headers, params=params, **kwargs
            )
    except httpx.HTTPError as exc:
        raise StoreError(f"store not reachable: {exc}") from exc
    if response.status_code >= 400:
        raise StoreError(_detail(response), status=response.status_code)
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise StoreError("store sent something unreadable") from exc


# ------------------------------------------------------------------- browsing

async def catalog(q: str = "") -> dict[str, Any]:
    params = {"app": APP, **({"q": q} if q else {})}
    return await _request("GET", "/api/catalog", params=params)


async def plugin(slug: str) -> dict[str, Any]:
    return await _request("GET", f"/api/catalog/{slug}", params={"app": APP})


async def download(url: str) -> bytes:
    """The archive behind a catalog `download_url`, up to the size limit.

    Only addresses on the store itself are fetched. The URL comes out of the
    catalog, and a catalog entry that pointed elsewhere would turn this into
    a way to make the backend fetch anything.
    """
    from .plugins import MAX_ARCHIVE_BYTES

    if not url.startswith(f"{STORE_URL}/api/download/"):
        raise StoreError("download address is not on the store")
    try:
        async with (
            httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client,
            client.stream("GET", url, params={"via": "app"},
                          headers={"User-Agent": "EdgeDash"}) as response,
        ):
            if response.status_code >= 400:
                await response.aread()
                raise StoreError(_detail(response), status=response.status_code)
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_ARCHIVE_BYTES:
                    raise StoreError("archive is larger than 64 MB")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise StoreError(f"download failed: {exc}") from exc
    return b"".join(chunks)


#: Images from a version's archive, kept for the window's lifetime. A detail
#: page asks for the same pictures again and again while someone clicks
#: through the screenshots; the store need not be asked each time.
_IMAGES: dict[str, tuple[bytes, str]] = {}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml")


async def image(url: str) -> tuple[bytes, str]:
    """An icon or screenshot the catalog names, fetched through the backend.

    Only addresses in the store's asset area are fetched, for the same reason
    as with downloads: the address comes out of the catalog.
    """
    if not url.startswith(f"{STORE_URL}/api/assets/"):
        raise StoreError("image address is not on the store", status=404)
    if url in _IMAGES:
        return _IMAGES[url]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False) as client:
            response = await client.get(url, headers={"User-Agent": "EdgeDash"})
    except httpx.HTTPError as exc:
        raise StoreError(f"store not reachable: {exc}") from exc
    if response.status_code >= 400:
        raise StoreError(_detail(response), status=response.status_code)
    kind = response.headers.get("content-type", "").split(";")[0].strip()
    if kind not in IMAGE_TYPES or len(response.content) > MAX_IMAGE_BYTES:
        raise StoreError("not an image", status=415)
    if len(_IMAGES) > 64:
        _IMAGES.clear()
    _IMAGES[url] = (response.content, kind)
    return _IMAGES[url]


# ------------------------------------------------------------------------ rating

async def rating(slug: str) -> dict[str, Any]:
    """Votes, your own vote and the latest comments."""
    return await _request("GET", f"/api/catalog/{slug}/rating", auth_if_present=True)


async def rate(slug: str, value: int, comment: str = "") -> dict[str, Any]:
    """Thumbs up (`1`) or down (`-1`), with a sentence if wanted. The store
    refuses a thumbs down without one."""
    if value not in (1, -1):
        raise StoreError("a vote is 1 or -1", status=422)
    return await _request("PUT", f"/api/catalog/{slug}/rating", auth=True,
                          json={"value": value, "comment": comment})


async def unrate(slug: str) -> dict[str, Any]:
    return await _request("DELETE", f"/api/catalog/{slug}/rating", auth=True)


# -------------------------------------------------------------------- signing in

async def device_start() -> dict[str, Any]:
    return await _request("POST", "/api/auth/device")


async def device_poll(device_code: str) -> dict[str, Any]:
    """Ask once whether the code was confirmed; keeps the token on success.

    `slow_down` does not mean "not yet" but "you ask too often". The window
    has to widen its interval, which is why `backoff` is passed on.
    """
    answer = await _request("POST", "/api/auth/device/poll", json={"device_code": device_code})
    status = answer.get("status", "pending")
    if status == "ok":
        write_token(answer["token"])
        return {"status": "ok", "user": answer.get("user")}
    if status == "slow_down":
        return {"status": "slow_down", "backoff": int(answer.get("backoff", 5))}
    return {"status": status}


async def me() -> dict[str, Any] | None:
    """Who is signed in, or None. A token the store no longer knows is dropped."""
    if not read_token():
        return None
    try:
        return await _request("GET", "/api/auth/me", auth=True)
    except StoreError as exc:
        if exc.status == 401:
            write_token("")
            return None
        raise


async def pending() -> dict[str, Any] | None:
    """What waits for review in the store, or None.

    Only accounts allowed to review get an answer (`plugin.review`); for
    everyone else the store says 403, and that is the normal case, not an
    error. The address of the review page comes from the store too.
    """
    if not read_token():
        return None
    try:
        answer = await _request("GET", "/api/review/pending", auth=True)
    except StoreError as exc:
        if exc.status in (401, 403):
            return None
        raise
    if not isinstance(answer, dict):
        return None
    return {"submissions": int(answer.get("submissions") or 0),
            "reports": int(answer.get("reports") or 0),
            "url": str(answer.get("url") or "")}


async def logout() -> None:
    if read_token():
        # Ending the session on the store is good manners, not needed:
        # without the token here nobody gets back in.
        with contextlib.suppress(StoreError):
            await _request("POST", "/api/auth/logout", auth=True)
    write_token("")


# --------------------------------------------------------------------- publishing

async def check_slug(slug: str) -> dict[str, Any]:
    return await _request("GET", f"/api/slugs/{slug}", params={"app": APP})


def pack(folder: Path) -> bytes:
    """A widget folder as the store expects it, with the folder as top level."""
    folder = folder.expanduser().resolve()
    if not (folder / "manifest.json").is_file():
        raise StoreError(f"there is no manifest.json in {folder}")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(folder)
            if any(part in SKIPPED_PARTS for part in relative.parts):
                continue
            if relative.suffix in (".pyc", ".pyo") or relative.name == ".install.json":
                continue
            archive.write(path, f"{folder.name}/{relative.as_posix()}")
    return buffer.getvalue()


async def upload(data: bytes, filename: str = "plugin.zip") -> dict[str, Any]:
    """Submit a finished archive to the store, as it is.

    ZIP, TAR and tar.gz all go: the store reads each of them and repacks
    what it ships as a ZIP, so nothing is converted here.
    """
    from .plugins import MAX_ARCHIVE_BYTES

    if len(data) > MAX_ARCHIVE_BYTES:
        raise StoreError("archive is larger than 64 MB")
    name = Path(filename).name.replace('"', "") or "plugin.zip"
    files = {"datei": (name, data, "application/octet-stream")}
    return await _request("POST", "/api/plugins", auth=True, files=files)


async def my_plugins() -> dict[str, Any]:
    """The signed-in author's plugins, only those for Edge Dash."""
    answer = await _request("GET", "/api/me/plugins", auth=True)
    plugins = [p for p in answer.get("plugins", []) if p.get("app", "deckswitch") == APP]
    return {"count": len(plugins), "plugins": plugins}


async def withdraw(slug: str, version: str) -> dict[str, Any]:
    return await _request("DELETE", f"/api/me/plugins/{slug}/{version}", auth=True)
