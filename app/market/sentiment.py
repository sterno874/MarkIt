from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen


def crypto_fear_greed() -> dict[str, Any]:
    req = Request(
        "https://api.alternative.me/fng/?limit=1",
        headers={"User-Agent": "market-desk/1.0"},
    )
    with urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    row = (data.get("data") or [{}])[0]
    return {
        "market": "crypto",
        "score": float(row.get("value", 0)),
        "rating": row.get("value_classification") or "—",
        "text": f"**Crypto Fear & Greed**: {row.get('value')} · {row.get('value_classification')}",
    }


def stock_fear_greed() -> dict[str, Any]:
    req = Request(
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.cnn.com/markets/fear-and-greed",
            "Origin": "https://www.cnn.com",
        },
    )
    with urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    fg = data.get("fear_and_greed") or {}
    score = float(fg.get("score") or 0)
    rating = (fg.get("rating") or "—").title()
    return {
        "market": "stocks",
        "score": score,
        "rating": rating,
        "previous_close": fg.get("previous_close"),
        "text": (
            f"**Stock Fear & Greed**: {score:.0f} · {rating}\n"
            f"Prev close {fg.get('previous_close')} · 1w {fg.get('previous_1_week')} · "
            f"1m {fg.get('previous_1_month')}"
        ),
        "raw": fg,
    }
