from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.config import SEC_USER_AGENT
from app.security import resolve

_TICKERS: dict[str, int] | None = None


def _headers() -> dict[str, str]:
    return {
        "User-Agent": SEC_USER_AGENT,
        "Accept": "application/json",
    }


def _get(url: str) -> Any:
    req = Request(url, headers=_headers())
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ticker_cik_map() -> dict[str, int]:
    global _TICKERS
    if _TICKERS is not None:
        return _TICKERS
    data = _get("https://www.sec.gov/files/company_tickers.json")
    mapping: dict[str, int] = {}
    for row in data.values():
        mapping[str(row["ticker"]).upper()] = int(row["cik_str"])
    _TICKERS = mapping
    return mapping


def cik_for(symbol: str) -> int | None:
    sec = resolve(symbol)
    root = (sec.underlying or sec.yahoo).split("-")[0].upper()
    return ticker_cik_map().get(root)


def recent_filings(symbol: str, forms: list[str] | None = None, limit: int = 8) -> dict[str, Any]:
    sec = resolve(symbol)
    cik = cik_for(sec.yahoo if sec.is_equity_like else (sec.underlying or sec.yahoo))
    if cik is None:
        raise ValueError(f"No SEC CIK mapped for {sec.yahoo}")
    pad = f"{cik:010d}"
    data = _get(f"https://data.sec.gov/submissions/CIK{pad}.json")
    recent = data.get("filings", {}).get("recent", {})
    forms_wanted = {f.upper() for f in (forms or [])} or None
    rows = []
    for i, form in enumerate(recent.get("form", [])):
        if forms_wanted and form.upper() not in forms_wanted:
            continue
        accession = recent["accessionNumber"][i]
        filed = recent["filingDate"][i]
        primary = recent["primaryDocument"][i]
        acc_nodash = accession.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{primary}"
        rows.append(
            {
                "form": form,
                "filed": filed,
                "accession": accession,
                "description": recent.get("primaryDocDescription", [""])[i] if recent.get("primaryDocDescription") else "",
                "url": url,
            }
        )
        if len(rows) >= limit:
            break
    lines = [f"**{sec.yahoo} SEC filings** (CIK {cik})"]
    for row in rows:
        lines.append(f"• `{row['form']}` {row['filed']} — [{row['description'] or 'doc'}]({row['url']})")
    if len(lines) == 1:
        lines.append("_No matching filings._")
    return {"security": sec, "cik": cik, "filings": rows, "text": "\n".join(lines)}


def company_search(query: str) -> list[dict[str, Any]]:
    data = _get(
        "https://efts.sec.gov/LATEST/search-index?"
        + f"q={quote(query)}&dateRange=custom&startdt=2020-01-01&forms=10-K,10-Q,8-K"
    )
    return data.get("hits", {}).get("hits", [])[:5]
