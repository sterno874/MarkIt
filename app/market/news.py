from __future__ import annotations

from typing import Any

import yfinance as yf

from app import format as fmt
from app.security import resolve


def company_news(symbol: str, limit: int = 6) -> dict[str, Any]:
    sec = resolve(symbol)
    items = yf.Ticker(sec.yahoo).news or []
    lines = [f"**{sec.yahoo} news**"]
    rows = []
    for item in items[:limit]:
        content = item.get("content") or item
        title = content.get("title") or "Untitled"
        provider = ""
        prov = content.get("provider") or {}
        if isinstance(prov, dict):
            provider = prov.get("displayName") or ""
        url = None
        for key in ("canonicalUrl", "clickThroughUrl"):
            blob = content.get(key)
            if isinstance(blob, dict) and blob.get("url"):
                url = blob["url"]
                break
            if isinstance(blob, str):
                url = blob
                break
        when = content.get("pubDate") or content.get("displayTime") or ""
        summary = content.get("summary") or content.get("description") or ""
        rows.append({"title": title, "url": url, "provider": provider, "when": when, "summary": summary})
        link = f"([link]({url}))" if url else ""
        lines.append(f"• **{title}** {link}\n  _{provider}_ · {str(when)[:16]}\n  {fmt.truncate(summary, 180)}")
    if len(lines) == 1:
        lines.append("_No recent headlines._")
    return {"security": sec, "items": rows, "text": "\n".join(lines)}
