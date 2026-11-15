from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

import yfinance as yf

from app.security import Security, resolve

_executor = ThreadPoolExecutor(max_workers=6)


def get_security(symbol: str) -> Security:
    return resolve(symbol)


def get_many(symbols: Iterable[str]) -> list[Security]:
    unique = list(dict.fromkeys(s.upper() for s in symbols))
    return list(_executor.map(resolve, unique))


def history(symbol: str, period: str = "6mo", interval: str = "1d"):
    return yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)


def peer_symbols(security: Security, limit: int = 6) -> list[str]:
    peers = security.raw.get("peerGroup") or []
    if isinstance(peers, str):
        peers = [p.strip() for p in peers.split(",") if p.strip()]
    if not peers:
        # Sector fallback: nothing perfect on Yahoo; leave empty.
        return []
    return [str(p).upper() for p in peers[:limit]]


def download_closes(symbols: list[str], period: str = "6mo"):
    if not symbols:
        return None
    return yf.download(
        " ".join(symbols),
        period=period,
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
