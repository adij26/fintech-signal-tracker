"""Optional one-paragraph AI summary of the day's signals, using the Claude API.

Skipped cleanly when ANTHROPIC_API_KEY isn't set, so the tracker works without it.
"""

from __future__ import annotations

import os

API_URL = "https://api.anthropic.com/v1/messages"

PROMPT = """You are writing the lead paragraph of a daily briefing on fintech and Office-of-the-CFO software
for a go-to-market professional. Using ONLY the data below, write 3-4 plain sentences on what stands out
today: notable IPO filings, market moves, and topics heating up in the news. Do not give investment advice,
do not speculate beyond the data, and do not invent facts. If the data is thin, say so briefly.

DATA:
{data}"""


def build_context(digest: dict) -> str:
    lines = []
    for f in digest.get("filings", [])[:8]:
        lines.append(f"IPO filing: {f['company']} filed {f['form']} on {f['filed']} ({f['industry']})")
    m = digest.get("market") or {}
    for g in m.get("group_summary", []):
        lines.append(f"Group {g['group']}: {g['avg_1m']}% over 1 month, {g['vs_bench']} pts vs {m.get('primary_benchmark') or 'benchmark'}")
    for r in m.get("gainers", []):
        lines.append(f"Gainer: {r['name']} {r['chg_5d']}% over 5 days")
    for r in m.get("losers", []):
        lines.append(f"Decliner: {r['name']} {r['chg_5d']}% over 5 days")
    for t in digest.get("trends", []):
        if t["signal"] in ("heating", "new", "cooling") and t["count"]:
            lines.append(f"Topic {t['topic']}: {t['count']} mentions ({t['signal']})")
    for n in digest.get("news", [])[:12]:
        lines.append(f"Headline ({n['source']}): {n['title']}")
    return "\n".join(lines)


def summarize(digest: dict, config: dict) -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    import requests

    cfg = config.get("summary", {})
    resp = requests.post(
        API_URL,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={
            "model": cfg.get("model", "claude-haiku-5-5"),
            "max_tokens": cfg.get("max_tokens", 400),
            "messages": [{"role": "user", "content": PROMPT.format(data=build_context(digest))}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return "".join(b.get("text", "") for b in resp.json().get("content", [])).strip() or None
