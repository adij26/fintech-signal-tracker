"""Build the static website (GitHub Pages) from every saved digest."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .digest import SIGNAL_ICONS, at_a_glance, fmt_pct

TEMPLATES = Path(__file__).with_name("templates")


def sparkline(values: list[float], width: int = 90, height: int = 24) -> str:
    if not values or len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    step = width / (len(values) - 1)
    pts = " ".join(f"{i * step:.1f},{height - 2 - (v - lo) / span * (height - 4):.1f}"
                   for i, v in enumerate(values))
    cls = "up" if values[-1] >= values[0] else "down"
    return (f'<svg class="spark {cls}" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            f'aria-hidden="true"><polyline points="{pts}" fill="none" stroke-width="1.6"/></svg>')


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    env.filters["pct"] = fmt_pct
    env.filters["spark"] = sparkline
    env.filters["nice_date"] = lambda s: date.fromisoformat(s).strftime("%a, %b %-d, %Y")
    env.globals["signal_label"] = SIGNAL_ICONS
    return env


def build_site(data_dir: Path, out_dir: Path, repo_url: str = "https://github.com/adij26/fintech-signal-tracker") -> int:
    files = sorted((data_dir / "digests").glob("*.json"), reverse=True)
    digests = [json.loads(f.read_text()) for f in files]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "d").mkdir(exist_ok=True)
    env = _env()
    page = env.get_template("digest.html")
    archive = [{"date": d["date"], "filings": len(d.get("filings") or []),
                "hot": [t["topic"] for t in d.get("trends", []) if t["signal"] == "heating"][:2]}
               for d in digests]

    for i, d in enumerate(digests):
        ctx = {"d": d, "glance": at_a_glance(d), "archive": archive[:30], "repo": repo_url,
               "root": "../", "newer": digests[i - 1]["date"] if i else None,
               "older": digests[i + 1]["date"] if i + 1 < len(digests) else None}
        (out_dir / "d" / f"{d['date']}.html").write_text(page.render(**ctx), encoding="utf-8")
        if i == 0:
            (out_dir / "index.html").write_text(page.render(**{**ctx, "root": ""}), encoding="utf-8")
    if not digests:
        (out_dir / "index.html").write_text("<p>No digests yet. The first one arrives on the next scheduled run.</p>")
    return len(digests)
