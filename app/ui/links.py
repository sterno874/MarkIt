from __future__ import annotations

from urllib.parse import quote

from app.security import Security


def external_links(sec: Security) -> list[tuple[str, str]]:
    symbol = sec.yahoo
    root = sec.underlying or symbol
    links: list[tuple[str, str]] = []

    if sec.is_fx:
        pair = symbol.replace("=X", "")
        if pair == "JPY":
            pair = "USDJPY"
        links.extend(
            [
                ("TradingView", f"https://www.tradingview.com/symbols/{pair}/"),
                ("Yahoo", f"https://finance.yahoo.com/quote/{quote(symbol)}"),
            ]
        )
    elif sec.is_crypto:
        base = symbol.replace("-USD", "").replace("-USDT", "")
        links.extend(
            [
                ("TradingView", f"https://www.tradingview.com/symbols/{base}USD/"),
                ("Yahoo", f"https://finance.yahoo.com/quote/{quote(symbol)}"),
                ("CoinGecko", f"https://www.coingecko.com/en/search?query={quote(base)}"),
            ]
        )
    elif sec.is_future:
        links.extend(
            [
                ("TradingView", f"https://www.tradingview.com/symbols/{symbol.replace('=', '')}/"),
                ("Yahoo", f"https://finance.yahoo.com/quote/{quote(symbol)}"),
            ]
        )
    elif sec.is_option:
        links.extend(
            [
                ("Yahoo", f"https://finance.yahoo.com/quote/{quote(symbol)}"),
                ("Underlying", f"https://finance.yahoo.com/quote/{quote(root)}"),
                ("Options", f"https://finance.yahoo.com/quote/{quote(root)}/options"),
            ]
        )
    elif sec.is_index:
        tv = symbol.lstrip("^")
        links.extend(
            [
                ("TradingView", f"https://www.tradingview.com/symbols/{tv}/"),
                ("Yahoo", f"https://finance.yahoo.com/quote/{quote(symbol)}"),
            ]
        )
    else:
        links.extend(
            [
                ("TradingView", f"https://www.tradingview.com/symbols/{root}/"),
                ("Yahoo", f"https://finance.yahoo.com/quote/{quote(root)}"),
                ("SEC", f"https://www.sec.gov/edgar/search/#/category=custom&entityName={quote(root)}"),
                ("Finviz", f"https://finviz.com/quote.ashx?t={quote(root)}"),
            ]
        )
        if sec.website:
            links.append(("Website", sec.website if sec.website.startswith("http") else f"https://{sec.website}"))
    return links
