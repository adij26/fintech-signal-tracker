import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from signal_tracker import edgar, market, news, trends
from signal_tracker.client import FixtureClient
from signal_tracker.run import main
from signal_tracker.site import sparkline

FIX = Path(__file__).resolve().parent / "fixtures"
CONFIG = yaml.safe_load((FIX / "config.yaml").read_text())
TODAY = date(2026, 11, 19)
NOW = datetime(2026, 11, 19, 14, tzinfo=timezone.utc)


@pytest.fixture
def client():
    return FixtureClient(FIX)


# ------------------------------------------------------------------ EDGAR

def test_clean_name():
    assert edgar.clean_name("IonQ, Inc.  (IONQ)  (CIK 0001824920)") == ("IonQ, Inc.", "IONQ")
    assert edgar.clean_name("Vaultline Financial, Inc.  (CIK 0002011001)") == ("Vaultline Financial, Inc.", "")


def test_edgar_excludes_spacs_and_merges_keywords(client):
    filings = edgar.fetch_ipo_filings(client, CONFIG, TODAY)
    names = [f["company"] for f in filings]
    assert "Fintech Acquisition Corp IX" not in names  # SIC 6770 = SPAC
    assert len(filings) == 3
    assert filings[0]["keywords"] == ["fintech", "payments platform"]
    assert filings[0]["url"].startswith("https://www.sec.gov/Archives/edgar/data/")
    assert filings[0]["industry"] == "Finance services"


def test_edgar_sends_date_window(client):
    edgar.fetch_ipo_filings(client, CONFIG, TODAY)
    assert all("efts.sec.gov" in u for u in client.requested)


# ------------------------------------------------------------------ Market

def test_parse_yahoo_skips_gaps():
    payload = {"chart": {"result": [{"indicators": {"quote": [{"close": [10, None, 11, 12]}]}}]}}
    assert market.parse_yahoo(payload) == [10, 11, 12]


def test_parse_yahoo_error():
    with pytest.raises(ValueError):
        market.parse_yahoo({"chart": {"result": None, "error": {"code": "Not Found"}}})


def test_metrics_math():
    closes = [100.0] * 60 + [110.0]
    m = market.metrics(closes)
    assert m["chg_1d"] == 10.0 and m["chg_5d"] == 10.0 and m["chg_3m"] is None
    assert m["off_high"] == 0.0


def test_watchlist_fallback_and_missing(client):
    data = market.fetch_watchlist(client, CONFIG)
    sources = {r["ticker"]: r["source"] for rows in data["groups"].values() for r in rows}
    assert sources["NOVA"] == "stooq"           # no Yahoo fixture -> Stooq fallback
    assert sources["LDGR"] == "yahoo"
    assert any(m.startswith("GHST") for m in data["missing"])  # no data anywhere
    assert data["gainers"][0]["ticker"] == "TAPP"
    assert data["losers"][0]["ticker"] == "ORBT"
    assert all(g["vs_bench"] is not None for g in data["group_summary"])


# ------------------------------------------------------------------ News & trends

def test_parse_rss_strips_publisher_suffix():
    xml = ('<rss><channel><item><title>Big news - Daily Ledger</title><link>https://x</link>'
           '<pubDate>Thu, 19 Nov 2026 10:00:00 +0000</pubDate><source>Daily Ledger</source></item></channel></rss>')
    item = news.parse_feed(xml, "search")[0]
    assert item["title"] == "Big news" and item["source"] == "Daily Ledger"


def test_news_dedupes_filters_and_survives_broken_feed(client):
    items, errors = news.fetch_news(client, CONFIG, NOW)
    titles = [i["title"] for i in items]
    assert len(titles) == len(set(titles))
    assert not any("Old story" in t for t in titles)     # outside the lookback window
    assert errors and errors[0].startswith("Broken Feed")
    assert items == sorted(items, key=lambda i: i["published"], reverse=True)


def test_trend_tagging_uses_word_boundaries():
    topics = {"IPOs": ["ipo"], "Regulation": ["occ"]}
    items = [{"title": "Fintech files for IPO", "summary": ""},
             {"title": "A soccer club launches a card", "summary": ""}]  # 'occ' inside 'soccer'
    trends.tag_items(items, topics)
    assert items[0]["topics"] == ["IPOs"] and items[1]["topics"] == []


def test_momentum_signals():
    history = {f"2026-11-{d:02d}": {"A": 1, "B": 4} for d in range(1, 11)}
    rows = {r["topic"]: r for r in trends.momentum({"A": 5, "B": 1}, history, "2026-11-19")}
    assert rows["A"]["signal"] == "heating"
    assert rows["B"]["signal"] == "cooling"
    assert trends.momentum({"A": 2}, {}, "2026-11-19")[0]["signal"] == "new"


def test_history_is_trimmed(tmp_path):
    path = tmp_path / "h.json"
    history = {f"2026-{m:02d}-01": {"A": 1} for m in range(1, 13)}
    trends.save_history(path, history, "2026-12-15", {"A": 3}, keep=5)
    saved = json.loads(path.read_text())
    assert len(saved) == 5 and "2026-12-15" in saved


# ------------------------------------------------------------------ End to end

def test_demo_run_end_to_end(tmp_path):
    assert main(["--demo", "--date", "2026-11-19", "--out", str(tmp_path)]) == 0
    md = (tmp_path / "digests" / "latest.md").read_text()
    assert "Demo data" in md and "Vaultline Financial" in md and "🔥 heating up" in md
    assert "unreachable: Broken Feed" in md
    html = (tmp_path / "site" / "index.html").read_text()
    assert "<svg class=\"spark" in html and "Tapp" in html
    assert (tmp_path / "site" / "d" / "2026-11-19.html").exists()
    saved = json.loads((tmp_path / "data" / "digests" / "2026-11-19.json").read_text())
    assert saved["demo"] is True and saved["summary"] is None  # no API key in tests


def test_second_day_builds_archive_links(tmp_path):
    main(["--demo", "--date", "2026-11-18", "--out", str(tmp_path)])
    main(["--demo", "--date", "2026-11-19", "--out", str(tmp_path)])
    html = (tmp_path / "site" / "index.html").read_text()
    assert "d/2026-11-18.html" in html
    older = (tmp_path / "site" / "d" / "2026-11-18.html").read_text()
    assert "../d/2026-11-19.html" in older


def test_every_source_down_still_writes_a_digest(tmp_path):
    empty = tmp_path / "nofixtures"
    empty.mkdir()
    from signal_tracker import run as run_mod
    d = run_mod.gather(FixtureClient(empty), CONFIG, TODAY, NOW, {})
    assert d["filings"] is None and d["market"] is None and d["news"] == []
    assert not any(h["ok"] for h in d["health"])


def test_sparkline():
    assert sparkline([1]) == ""
    assert 'class="spark up"' in sparkline([1, 2, 3])
    assert 'class="spark down"' in sparkline([3, 2, 1])


def test_summary_skipped_without_key(monkeypatch):
    from signal_tracker import summarize
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert summarize.summarize({"filings": []}, CONFIG) is None


def test_summary_request_shape(monkeypatch):
    from signal_tracker import summarize
    import requests
    sent = {}

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"content": [{"type": "text", "text": "Quiet day."}]}

    def fake_post(url, headers, json, timeout):
        sent.update(url=url, headers=headers, body=json)
        return Resp()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(requests, "post", fake_post)
    digest = {"filings": [{"company": "Vaultline", "form": "S-1", "filed": "2026-11-17", "industry": "Finance"}],
              "market": None, "trends": [], "news": []}
    assert summarize.summarize(digest, CONFIG) == "Quiet day."
    assert sent["headers"]["x-api-key"] == "test-key"
    assert sent["body"]["model"] == CONFIG["summary"]["model"]
    assert "Vaultline" in sent["body"]["messages"][0]["content"]
