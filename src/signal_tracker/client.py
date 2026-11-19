"""HTTP access, swappable for saved fixtures in tests and demo mode."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

DEFAULT_UA = "fintech-signal-tracker (github.com/adij26/fintech-signal-tracker; adij26@users.noreply.github.com)"


class FetchError(Exception):
    pass


class LiveClient:
    """Real network access with a polite User-Agent, timeouts and one retry."""

    def __init__(self, user_agent: str | None = None, timeout: int = 20) -> None:
        import requests

        self.session = requests.Session()
        # SEC asks automated tools to identify themselves with contact details.
        self.session.headers["User-Agent"] = user_agent or os.environ.get("SEC_USER_AGENT") or DEFAULT_UA
        self.timeout = timeout

    def _get(self, url: str, params: dict | None = None):
        last = None
        for attempt in range(2):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp
                last = FetchError(f"HTTP {resp.status_code} from {url}")
                if resp.status_code in (400, 401, 403, 404):
                    break
            except Exception as exc:  # connection errors, timeouts
                last = FetchError(f"{type(exc).__name__}: {exc}")
            time.sleep(1.5 * (attempt + 1))
        raise last or FetchError(url)

    def get_json(self, url: str, params: dict | None = None):
        return self._get(url, params).json()

    def get_text(self, url: str, params: dict | None = None) -> str:
        return self._get(url, params).text


class FixtureClient:
    """Serves saved responses from a folder, routed by URL. Used by tests and --demo."""

    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)
        self.requested: list[str] = []

    def _path(self, url: str, params: dict | None = None) -> Path:
        if "efts.sec.gov" in url:
            return self.folder / "edgar.json"
        if (m := re.search(r"/v8/finance/chart/([A-Z.^-]+)", url)):
            return self.folder / "yahoo" / f"{m.group(1)}.json"
        if "stooq.com" in url:
            return self.folder / "stooq" / f"{(params or {}).get('s', 'unknown')}.csv"
        slug = re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")[-60:]
        return self.folder / "feeds" / f"{slug}.xml"

    def _read(self, url: str, params: dict | None = None) -> str:
        self.requested.append(url)
        path = self._path(url, params)
        if not path.exists():
            raise FetchError(f"no fixture for {url} (looked for {path.name})")
        return path.read_text(encoding="utf-8")

    def get_json(self, url: str, params: dict | None = None):
        import json

        return json.loads(self._read(url, params))

    def get_text(self, url: str, params: dict | None = None) -> str:
        return self._read(url, params)
