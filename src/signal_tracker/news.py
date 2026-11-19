"""Headlines from RSS / Atom feeds, parsed with the standard library."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

ATOM = "{http://www.w3.org/2005/Atom}"


def _strip(text: str | None) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def _date(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_feed(xml_text: str, source: str) -> list[dict]:
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    items = []
    for node in root.iter("item"):  # RSS 2.0
        title = _strip(node.findtext("title"))
        # Google News appends " - Publisher" to titles and gives it in <source>.
        publisher = _strip(node.findtext("source")) or source
        if publisher != source and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3]
        items.append({
            "title": title,
            "url": (node.findtext("link") or "").strip(),
            "published": _date(node.findtext("pubDate")),
            "summary": _strip(node.findtext("description"))[:280],
            "source": publisher,
            "feed": source,
        })
    for node in root.iter(f"{ATOM}entry"):  # Atom
        link = node.find(f"{ATOM}link")
        items.append({
            "title": _strip(node.findtext(f"{ATOM}title")),
            "url": link.get("href", "") if link is not None else "",
            "published": _date(node.findtext(f"{ATOM}updated") or node.findtext(f"{ATOM}published")),
            "summary": _strip(node.findtext(f"{ATOM}summary"))[:280],
            "source": source,
            "feed": source,
        })
    return [i for i in items if i["title"]]


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower())[:80]


def fetch_news(client, config: dict, now: datetime) -> tuple[list[dict], list[str]]:
    cfg = config["news"]
    cutoff = now - timedelta(days=cfg.get("lookback_days", 3))
    seen, items, errors = set(), [], []
    for name, url in cfg["feeds"].items():
        try:
            parsed = parse_feed(client.get_text(url), name)
        except Exception as exc:
            errors.append(f"{name} ({exc})")
            continue
        for item in parsed:
            key = _norm(item["title"])
            if key in seen or (item["published"] and item["published"] < cutoff):
                continue
            seen.add(key)
            items.append(item)
    if not items and len(errors) == len(cfg["feeds"]):
        raise RuntimeError("no feeds reachable")
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    items.sort(key=lambda i: i["published"] or epoch, reverse=True)
    return items, errors
