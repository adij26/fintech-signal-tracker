"""IPO signals: recent S-1 / F-1 registration statements from SEC EDGAR full-text search."""

from __future__ import annotations

import re
from datetime import date, timedelta

EFTS_URL = "https://efts.sec.gov/LATEST/search-index"

SIC_LABELS = {
    "6022": "State commercial banks", "6099": "Functions related to depository banking",
    "6141": "Personal credit institutions", "6153": "Short-term business credit",
    "6159": "Misc. business credit", "6199": "Finance services", "6211": "Security brokers & dealers",
    "6282": "Investment advice", "6770": "Blank check (SPAC)", "7370": "Computer services",
    "7372": "Prepackaged software", "7374": "Computer processing & data prep", "7389": "Business services",
}


def clean_name(display_name: str) -> tuple[str, str]:
    """'Ledgerline, Inc.  (LDGR)  (CIK 0001234567)' -> ('Ledgerline, Inc.', 'LDGR')."""
    name = re.split(r"\s+\(", display_name, maxsplit=1)[0].strip()
    ticker = ""
    parts = re.findall(r"\(([^)]*)\)", display_name)
    if parts and not parts[0].startswith("CIK"):
        ticker = parts[0].split(",")[0].strip()
    return name, ticker


def filing_url(hit: dict) -> str:
    src = hit.get("_source", {})
    adsh = src.get("adsh") or hit.get("_id", "").split(":")[0]
    ciks = src.get("ciks") or ["0"]
    cik = int(ciks[0])
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/{adsh}-index.htm"


def parse_hits(payload: dict, keyword: str) -> list[dict]:
    out = []
    for hit in payload.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        names = src.get("display_names") or ["Unknown filer"]
        name, ticker = clean_name(names[0])
        sics = src.get("sics") or []
        out.append({
            "company": name,
            "ticker": ticker,
            "cik": (src.get("ciks") or [""])[0],
            "form": src.get("form", ""),
            "filed": src.get("file_date", ""),
            "sic": sics[0] if sics else "",
            "industry": SIC_LABELS.get(sics[0], f"SIC {sics[0]}") if sics else "Unknown",
            "state": (src.get("biz_states") or [""])[0],
            "url": filing_url(hit),
            "keywords": [keyword],
        })
    return out


def fetch_ipo_filings(client, config: dict, today: date) -> list[dict]:
    cfg = config["edgar"]
    start = today - timedelta(days=cfg.get("lookback_days", 30))
    by_company: dict[str, dict] = {}
    errors = []
    for kw in cfg["keywords"]:
        params = {
            "q": f'"{kw}"',
            "forms": ",".join(cfg["forms"]),
            "dateRange": "custom",
            "startdt": start.isoformat(),
            "enddt": today.isoformat(),
        }
        try:
            payload = client.get_json(EFTS_URL, params)
        except Exception as exc:
            errors.append(f"{kw}: {exc}")
            continue
        for f in parse_hits(payload, kw):
            if f["sic"] in cfg.get("exclude_sics", []):
                continue
            key = f["cik"] or f["company"]
            if key in by_company:
                existing = by_company[key]
                existing["keywords"] = sorted(set(existing["keywords"]) | set(f["keywords"]))
                if f["filed"] > existing["filed"]:
                    existing.update({k: f[k] for k in ("form", "filed", "url")})
            else:
                by_company[key] = f

    if errors and not by_company and len(errors) == len(cfg["keywords"]):
        raise RuntimeError("EDGAR unavailable: " + errors[0])

    filings = sorted(by_company.values(), key=lambda f: (len(f["keywords"]), f["filed"]), reverse=True)
    return filings[: cfg.get("max_results", 25)]
