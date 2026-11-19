"""Market data for the watchlist: Yahoo Finance's chart endpoint, with Stooq as a fallback."""

from __future__ import annotations

import csv
import io
from statistics import mean

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
STOOQ_URL = "https://stooq.com/q/d/l/"


def parse_yahoo(payload: dict) -> list[float]:
    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not result:
        err = payload.get("chart", {}).get("error") or "empty result"
        raise ValueError(f"Yahoo: {err}")
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    closes = [c for c in quote.get("close", []) if c is not None]
    if not closes:
        raise ValueError("Yahoo: no closing prices")
    return closes


def parse_stooq(text: str) -> list[float]:
    rows = list(csv.DictReader(io.StringIO(text)))
    closes = [float(r["Close"]) for r in rows if r.get("Close") not in (None, "", "N/D")]
    if not closes:
        raise ValueError("Stooq: no data")
    return closes


def pct(new: float, old: float) -> float | None:
    return round(100 * (new / old - 1), 2) if old else None


def metrics(closes: list[float]) -> dict:
    last = closes[-1]

    def back(n: int):
        return pct(last, closes[-1 - n]) if len(closes) > n else None

    high = max(closes[-252:])
    return {
        "price": round(last, 2),
        "chg_1d": back(1),
        "chg_5d": back(5),
        "chg_1m": back(21),
        "chg_3m": back(63),
        "off_high": pct(last, high),  # % below the 52-week (or available) high
        "spark": [round(c, 2) for c in closes[-30:]],
    }


def fetch_closes(client, ticker: str) -> tuple[list[float], str]:
    try:
        payload = client.get_json(YAHOO_URL.format(ticker=ticker), {"range": "1y", "interval": "1d"})
        return parse_yahoo(payload), "yahoo"
    except Exception as first:
        try:
            text = client.get_text(STOOQ_URL, {"s": f"{ticker.lower()}.us", "i": "d"})
            return parse_stooq(text), "stooq"
        except Exception:
            raise first


def fetch_watchlist(client, config: dict) -> dict:
    wl = config["watchlist"]
    out = {"benchmarks": [], "groups": {}, "missing": []}

    def one(ticker: str, name: str):
        try:
            closes, source = fetch_closes(client, ticker)
            return {"ticker": ticker, "name": name, "source": source, **metrics(closes)}
        except Exception as exc:
            out["missing"].append(f"{ticker} ({exc})")
            return None

    for t, name in wl.get("benchmarks", {}).items():
        if (row := one(t, name)):
            out["benchmarks"].append(row)
    for group, tickers in wl.get("groups", {}).items():
        rows = [r for t, name in tickers.items() if (r := one(t, name))]
        if rows:
            out["groups"][group] = rows

    everything = [r for rows in out["groups"].values() for r in rows]
    if not everything and not out["benchmarks"]:
        raise RuntimeError("no market data from any source")

    # Groups are compared with the first benchmark listed in the config.
    primary = out["benchmarks"][0] if out["benchmarks"] else {}
    out["primary_benchmark"] = primary.get("name")
    spy_1m = primary.get("chg_1m")
    out["group_summary"] = []
    for group, rows in out["groups"].items():
        vals = [r["chg_1m"] for r in rows if r["chg_1m"] is not None]
        avg = round(mean(vals), 2) if vals else None
        out["group_summary"].append({
            "group": group, "avg_1m": avg,
            "vs_bench": round(avg - spy_1m, 2) if avg is not None and spy_1m is not None else None,
        })
    ranked = sorted((r for r in everything if r["chg_5d"] is not None), key=lambda r: r["chg_5d"])
    out["losers"] = ranked[:3]
    out["gainers"] = list(reversed(ranked[-3:]))
    return out
