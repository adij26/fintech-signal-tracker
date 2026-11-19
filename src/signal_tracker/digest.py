"""Render a digest (a plain dict) as Markdown."""

from __future__ import annotations

from datetime import date

SIGNAL_ICONS = {"heating": "🔥 heating up", "new": "🆕 new", "steady": "→ steady",
                "cooling": "❄️ cooling", "quiet": "· quiet"}


def fmt_pct(v) -> str:
    if v is None:
        return "–"
    arrow = "▲" if v > 0 else "▼" if v < 0 else ""
    return f"{arrow}{abs(v):.1f}%"


def at_a_glance(d: dict) -> list[str]:
    out = []
    filings = d.get("filings") or []
    if filings:
        out.append(f"**{len(filings)}** fintech-related IPO filing{'s' if len(filings) != 1 else ''} "
                   f"in the last {d['config_lookback']} days, most recently **{filings[0]['company']}** ({filings[0]['filed']}).")
    m = d.get("market")
    if m and m.get("gainers"):
        g, l = m["gainers"][0], m["losers"][0]
        out.append(f"Biggest 5-day move up: **{g['name']}** {fmt_pct(g['chg_5d'])}; "
                   f"down: **{l['name']}** {fmt_pct(l['chg_5d'])}.")
    hot = [t["topic"] for t in d.get("trends", []) if t["signal"] == "heating"]
    if hot:
        out.append("Heating up in the news: " + ", ".join(f"**{t}**" for t in hot[:3]) + ".")
    return out


def to_markdown(d: dict) -> str:
    day = date.fromisoformat(d["date"])
    L = [f"# Fintech & OCFO Signals: {day.strftime('%A, %B %-d, %Y')}", ""]
    if d.get("demo"):
        L += ["> ⚠️ **Demo data.** Every company, ticker, price and headline below is fictional.", ""]
    if d.get("summary"):
        L += [f"> {d['summary']}", "", "<sub>Summary written by Claude from the data below.</sub>", ""]
    glance = at_a_glance(d)
    if glance:
        L += ["## At a glance", ""] + [f"- {g}" for g in glance] + [""]

    L += ["## 🚀 IPO signals", "",
          f"S-1 / F-1 registration statements filed in the last {d['config_lookback']} days that mention "
          "fintech or finance-software terms. A filing is an early signal, not a guarantee of a listing.", ""]
    if d.get("filings"):
        L += ["| Company | Form | Filed | Industry | Matched terms |", "|---|---|---|---|---|"]
        for f in d["filings"]:
            L.append(f"| [{f['company']}]({f['url']}) | {f['form']} | {f['filed']} | {f['industry']} "
                     f"| {', '.join(f['keywords'])} |")
    else:
        L.append("_No matching filings in this window._")
    L.append("")

    m = d.get("market")
    L += ["## 📈 Market", ""]
    if m:
        if m.get("benchmarks"):
            L.append("Benchmarks: " + " · ".join(
                f"{b['name']} {fmt_pct(b['chg_1d'])} today, {fmt_pct(b['chg_1m'])} 1M" for b in m["benchmarks"]))
            L.append("")
        L += [f"| Group | Avg 1M | vs {m.get('primary_benchmark') or 'benchmark'} |", "|---|---:|---:|"]
        for g in m.get("group_summary", []):
            vs = "–" if g["vs_bench"] is None else f"{g['vs_bench']:+.1f} pts"
            L.append(f"| {g['group']} | {fmt_pct(g['avg_1m'])} | {vs} |")
        L.append("")
        for group, rows in m["groups"].items():
            L += [f"**{group}**", "", "| Ticker | Company | Price | 1D | 5D | 1M | Off high |",
                  "|---|---|---:|---:|---:|---:|---:|"]
            for r in rows:
                L.append(f"| {r['ticker']} | {r['name']} | {r['price']:,.2f} | {fmt_pct(r['chg_1d'])} "
                         f"| {fmt_pct(r['chg_5d'])} | {fmt_pct(r['chg_1m'])} | {fmt_pct(r['off_high'])} |")
            L.append("")
    else:
        L += ["_Market data unavailable today._", ""]

    L += ["## 🔥 Trends in the headlines", "", "| Topic | Mentions today | Recent avg | Signal |",
          "|---|---:|---:|---|"]
    for t in d.get("trends", []):
        avg = "–" if t["avg"] is None else f"{t['avg']:g}"
        L.append(f"| {t['topic']} | {t['count']} | {avg} | {SIGNAL_ICONS[t['signal']]} |")
    L.append("")

    L += ["## 📰 Headlines", ""]
    for n in d.get("news", []):
        when = n["published"][:10] if n.get("published") else ""
        tags = f" · _{', '.join(n['topics'])}_" if n.get("topics") else ""
        L.append(f"- [{n['title']}]({n['url']}): {n['source']}{' · ' + when if when else ''}{tags}")
    if not d.get("news"):
        L.append("_No headlines today._")
    L.append("")

    L += ["## Source health", ""]
    for s in d.get("health", []):
        L.append(f"- {'✅' if s['ok'] else '⚠️'} **{s['source']}**: {s['detail']}")
    L += ["", "---", "*Generated automatically by "
          "[fintech-signal-tracker](https://github.com/adij26/fintech-signal-tracker). "
          "Public data only. Not investment advice.*", ""]
    return "\n".join(L)
