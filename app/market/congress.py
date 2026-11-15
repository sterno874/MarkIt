from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app import format as fmt


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    query = f"?{urlencode(params)}" if params else ""
    url = f"https://www.bargo.ai/free-apis/congress/v1{path}{query}"
    req = Request(url, headers={"User-Agent": "market-desk/1.0", "Accept": "application/json"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def recent_trades(ticker: str | None = None, limit: int = 10) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": min(limit, 50)}
    if ticker:
        params["ticker"] = ticker.upper()
        data = _get(f"/trades/{ticker.upper()}", {"limit": params["limit"]})
    else:
        data = _get("/trades", params)
    trades = data.get("trades") or data.get("data") or []
    lines = [f"**Congressional trades**" + (f" · `{ticker.upper()}`" if ticker else "")]
    for trade in trades[:limit]:
        member = trade.get("member") or "Unknown"
        chamber = (trade.get("chamber") or "").title()
        tkr = trade.get("ticker") or "?"
        side = (trade.get("type") or "").title()
        amount = trade.get("amount_range") or f"{fmt.money(trade.get('amount_low'))}–{fmt.money(trade.get('amount_high'))}"
        tx = trade.get("transaction_date")
        disc = trade.get("disclosure_date")
        perf = trade.get("perf_pct")
        perf_s = f" · since {fmt.pct(perf, already_percent=True)}" if perf is not None else ""
        lines.append(
            f"• **{member}** ({chamber}) `{tkr}` {side} {amount}\n"
            f"  traded {tx} · disclosed {disc}{perf_s}"
        )
    if len(lines) == 1:
        lines.append("_No recent disclosures in the free window._")
    return {"trades": trades, "text": "\n".join(lines)}
