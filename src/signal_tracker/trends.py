"""Count topic mentions in headlines and compare them with the recent average.

History is kept in data/trend_history.json and committed back to the repo by the
scheduled workflow, so the tracker's memory grows a little with every run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import mean

HISTORY_WINDOW = 20  # runs (about four weeks of weekdays)


def tag_items(items: list[dict], topics: dict[str, list[str]]) -> None:
    patterns = {t: re.compile("|".join(rf"\b{re.escape(p.strip())}\b" for p in phrases), re.I)
                for t, phrases in topics.items()}
    for item in items:
        text = f"{item['title']} {item.get('summary', '')}"
        item["topics"] = [t for t, pat in patterns.items() if pat.search(text)]


def count_topics(items: list[dict], topics: dict) -> dict[str, int]:
    counts = {t: 0 for t in topics}
    for item in items:
        for t in item.get("topics", []):
            counts[t] += 1
    return counts


def load_history(path: Path) -> dict[str, dict[str, int]]:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def momentum(counts: dict[str, int], history: dict[str, dict[str, int]], today: str) -> list[dict]:
    past_days = sorted(d for d in history if d < today)[-HISTORY_WINDOW:]
    rows = []
    for topic, count in counts.items():
        past = [history[d].get(topic, 0) for d in past_days]
        avg = mean(past) if past else None
        if avg is None or len(past) < 3:
            signal = "new" if count else "quiet"
        elif count >= 3 and count >= 1.5 * max(avg, 1):
            signal = "heating"
        elif avg >= 2 and count <= 0.5 * avg:
            signal = "cooling"
        else:
            signal = "steady" if count else "quiet"
        rows.append({"topic": topic, "count": count,
                     "avg": round(avg, 1) if avg is not None else None, "signal": signal})
    order = {"heating": 0, "new": 1, "steady": 2, "cooling": 3, "quiet": 4}
    return sorted(rows, key=lambda r: (order[r["signal"]], -r["count"]))


def save_history(path: Path, history: dict, today: str, counts: dict[str, int], keep: int = 120) -> None:
    history[today] = counts
    trimmed = {d: history[d] for d in sorted(history)[-keep:]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trimmed, indent=1, sort_keys=True))
