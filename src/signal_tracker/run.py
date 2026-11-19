"""Run the tracker: gather every source, save the digest, rebuild the site.

    python -m signal_tracker              # live run, writes data/, digests/ and site/
    python -m signal_tracker --demo       # offline run on fictional fixture data
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from . import edgar, market, news, summarize, trends
from .client import FixtureClient, LiveClient
from .digest import to_markdown
from .site import build_site

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"


def gather(client, config: dict, today: date, now: datetime, history: dict) -> dict:
    """Collect every source. One failing source never stops the digest."""
    d = {"date": today.isoformat(), "generated_at": now.isoformat(timespec="minutes"),
         "config_lookback": config["edgar"].get("lookback_days", 30), "health": []}

    def ok(source, detail):
        d["health"].append({"source": source, "ok": True, "detail": detail})

    def bad(source, exc):
        d["health"].append({"source": source, "ok": False, "detail": str(exc)[:200]})

    try:
        d["filings"] = edgar.fetch_ipo_filings(client, config, today)
        ok("SEC EDGAR", f"{len(d['filings'])} matching filings")
    except Exception as exc:
        d["filings"] = None
        bad("SEC EDGAR", exc)

    try:
        d["market"] = market.fetch_watchlist(client, config)
        n = sum(len(r) for r in d["market"]["groups"].values())
        miss = d["market"]["missing"]
        detail = f"{n} tickers" + (f"; missing {', '.join(m.split(' ')[0] for m in miss)}" if miss else "")
        (ok if not miss else bad)("Market data", detail)
    except Exception as exc:
        d["market"] = None
        bad("Market data", exc)

    try:
        items, errors = news.fetch_news(client, config, now)
        trends.tag_items(items, config["trends"])
        counts = trends.count_topics(items, config["trends"])
        d["trends"] = trends.momentum(counts, history, d["date"])
        d["trend_counts"] = counts
        cap = config["news"].get("max_items", 25)
        d["news"] = [{**i, "published": i["published"].isoformat() if i["published"] else None}
                     for i in items[:cap]]
        detail = f"{len(items)} headlines from {len(config['news']['feeds']) - len(errors)} feeds"
        if errors:
            bad("News feeds", detail + "; unreachable: " + ", ".join(e.split(" (")[0] for e in errors))
        else:
            ok("News feeds", detail)
    except Exception as exc:
        d["news"], d["trends"], d["trend_counts"] = [], [], {}
        bad("News feeds", exc)

    try:
        d["summary"] = summarize.summarize(d, config)
        if d["summary"]:
            ok("AI summary", config.get("summary", {}).get("model", ""))
    except Exception as exc:
        d["summary"] = None
        bad("AI summary", exc)
    return d


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="signal-tracker", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=str(ROOT / "config.yaml"))
    p.add_argument("--out", default=str(ROOT), help="folder for data/, digests/ and site/")
    p.add_argument("--date", help="run as if today were YYYY-MM-DD")
    p.add_argument("--demo", action="store_true", help="use fictional fixture data; no network")
    p.add_argument("--site-only", action="store_true", help="just rebuild the site from saved digests")
    args = p.parse_args(argv)

    out = Path(args.out)
    if args.site_only:
        n = build_site(out / "data", out / "site")
        print(f"site rebuilt from {n} digests")
        return 0

    config_path = FIXTURES / "config.yaml" if args.demo else Path(args.config)
    config = yaml.safe_load(Path(config_path).read_text())
    client = FixtureClient(FIXTURES) if args.demo else LiveClient()
    today = date.fromisoformat(args.date) if args.date else datetime.now(timezone.utc).date()
    now = datetime.combine(today, datetime.now(timezone.utc).time(), timezone.utc) if args.date \
        else datetime.now(timezone.utc)

    history_path = out / "data" / "trend_history.json"
    history = trends.load_history(history_path)
    if args.demo and not history:
        history = trends.load_history(FIXTURES / "trend_history.json")
    d = gather(client, config, today, now, history)
    d["demo"] = args.demo

    (out / "data" / "digests").mkdir(parents=True, exist_ok=True)
    (out / "digests").mkdir(parents=True, exist_ok=True)
    (out / "data" / "digests" / f"{d['date']}.json").write_text(json.dumps(d, indent=1, default=str))
    md = to_markdown(d)
    (out / "digests" / f"{d['date']}.md").write_text(md, encoding="utf-8")
    (out / "digests" / "latest.md").write_text(md, encoding="utf-8")
    if d.get("trend_counts"):
        trends.save_history(history_path, history, d["date"], d["trend_counts"])
    n = build_site(out / "data", out / "site")

    for h in d["health"]:
        print(f"{'✓' if h['ok'] else '!'} {h['source']}: {h['detail']}")
    print(f"digest for {d['date']} written; site has {n} day(s)")
    # Fail the run only if every core source failed, so a flaky feed doesn't break the schedule.
    core_ok = any(h["ok"] for h in d["health"] if h["source"] in ("SEC EDGAR", "Market data", "News feeds"))
    return 0 if core_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
