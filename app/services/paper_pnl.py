"""Paper trading mark-to-market, attribution, and leaderboards."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app import format as fmt
from app.db import db
from app.market.quotes import get_many


def pnl_dollars(side: str, entry: float, last: float, qty: float) -> float:
    if side == "long":
        return (last - entry) * qty
    return (entry - last) * qty


def pnl_pct(side: str, entry: float, last: float) -> float:
    if not entry:
        return 0.0
    if side == "long":
        return (last - entry) / entry * 100
    return (entry - last) / entry * 100


@dataclass
class PositionView:
    id: int
    user_id: int
    symbol: str
    side: str
    qty: float
    entry: float
    last: float | None
    unrealized_dollars: float | None
    unrealized_pct: float | None
    note: str | None = None


@dataclass
class TraderBook:
    user_id: int
    realized: float = 0.0
    unrealized: float = 0.0
    open_count: int = 0
    closed_count: int = 0
    positions: list[PositionView] = field(default_factory=list)

    @property
    def total(self) -> float:
        return self.realized + self.unrealized


@dataclass
class ServerBook:
    traders: list[TraderBook]
    open_positions: list[PositionView]
    prices: dict[str, float]

    @property
    def realized(self) -> float:
        return sum(t.realized for t in self.traders)

    @property
    def unrealized(self) -> float:
        return sum(t.unrealized for t in self.traders)

    @property
    def total(self) -> float:
        return self.realized + self.unrealized


def _mark_positions(rows: list[Any], prices: dict[str, float]) -> list[PositionView]:
    out: list[PositionView] = []
    for r in rows:
        sym = r["symbol"]
        last = prices.get(sym)
        entry = float(r["entry"])
        qty = float(r["qty"])
        side = r["side"]
        u_dollars = pnl_dollars(side, entry, last, qty) if last is not None else None
        u_pct = pnl_pct(side, entry, last) if last is not None else None
        note = None
        try:
            note = r["note"]
        except (KeyError, IndexError):
            note = None
        out.append(
            PositionView(
                id=int(r["id"]),
                user_id=int(r["user_id"]),
                symbol=sym,
                side=side,
                qty=qty,
                entry=entry,
                last=last,
                unrealized_dollars=u_dollars,
                unrealized_pct=u_pct,
                note=note,
            )
        )
    return out


def load_prices(symbols: list[str]) -> dict[str, float]:
    unique = sorted({s.upper() for s in symbols if s})
    if not unique:
        return {}
    prices: dict[str, float] = {}
    for sec in get_many(unique):
        if sec.last is not None:
            prices[sec.yahoo.upper()] = float(sec.last)
            # Also key by requested symbol forms
            prices[sec.symbol.upper()] = float(sec.last)
    # Ensure original keys resolve when yahoo differs
    for sym in unique:
        if sym not in prices:
            # try normalized yahoo from get_many results already covered
            pass
    return prices


def build_server_book(guild_id: int) -> ServerBook:
    open_rows = db.paper_list(guild_id, user_id=None)
    symbols = [r["symbol"] for r in open_rows]
    prices = load_prices(symbols)
    # Map by yahoo-insensitive: get_many returns yahoo; also try raw symbol
    priced: dict[str, float] = {}
    for r in open_rows:
        sym = r["symbol"].upper()
        if sym in prices:
            priced[sym] = prices[sym]
        else:
            # fuzzy: any price key ending with same root
            for k, v in prices.items():
                if k == sym or k.replace("-USD", "") == sym:
                    priced[sym] = v
                    break

    positions = _mark_positions(open_rows, priced)
    realized_map = db.paper_realized_by_user(guild_id)
    closed_counts = db.paper_closed_counts(guild_id)

    by_user: dict[int, TraderBook] = {}
    for uid in db.paper_trader_ids(guild_id):
        by_user[uid] = TraderBook(
            user_id=uid,
            realized=realized_map.get(uid, 0.0),
            closed_count=closed_counts.get(uid, 0),
        )

    for pos in positions:
        book = by_user.setdefault(pos.user_id, TraderBook(user_id=pos.user_id))
        book.positions.append(pos)
        book.open_count += 1
        if pos.unrealized_dollars is not None:
            book.unrealized += pos.unrealized_dollars

    traders = sorted(by_user.values(), key=lambda t: t.total, reverse=True)
    return ServerBook(traders=traders, open_positions=positions, prices=priced)


def build_trader_book(guild_id: int, user_id: int) -> TraderBook:
    server = build_server_book(guild_id)
    for t in server.traders:
        if t.user_id == user_id:
            return t
    return TraderBook(user_id=user_id)


def format_leaderboard(book: ServerBook, *, limit: int = 15) -> str:
    if not book.traders:
        return "No paper trades yet. `/paper buy symbol:AAPL` to start."
    lines = [
        f"**Server total** {fmt.money(book.total)} "
        f"(realized {fmt.money(book.realized)} · open {fmt.money(book.unrealized)})",
        "",
        "**Leaderboard**",
    ]
    for i, t in enumerate(book.traders[:limit], start=1):
        lines.append(
            f"**#{i}** <@{t.user_id}> **{fmt.money(t.total)}** "
            f"(realized {fmt.money(t.realized)} · open {fmt.money(t.unrealized)}) "
            f"· {t.open_count} open / {t.closed_count} closed"
        )
    return "\n".join(lines)


def format_trader(book: TraderBook, *, include_history: bool = True, guild_id: int | None = None) -> str:
    lines = [
        f"**Trader** <@{book.user_id}>",
        f"Total **{fmt.money(book.total)}** · realized {fmt.money(book.realized)} · "
        f"unrealized {fmt.money(book.unrealized)}",
        f"Open `{book.open_count}` · Closed `{book.closed_count}`",
    ]
    if book.positions:
        lines.append("")
        lines.append("**Open positions**")
        for p in book.positions:
            lines.append(
                f"#{p.id} {p.side} `{p.symbol}` x{p.qty} @ {fmt.number(p.entry)} → "
                f"{fmt.number(p.last)} ({fmt.money(p.unrealized_dollars)} / "
                f"{fmt.pct(p.unrealized_pct, already_percent=True)})"
            )
    if include_history and guild_id is not None:
        closed = db.paper_closed_list(guild_id, book.user_id, limit=8)
        if closed:
            lines.append("")
            lines.append("**Recent closed**")
            for c in closed:
                lines.append(
                    f"`{c['symbol']}` {c['side']} x{c['qty']} "
                    f"{fmt.number(c['entry'])}→{fmt.number(c['exit'])} "
                    f"**{fmt.money(c['pnl_dollars'])}** ({fmt.pct(c['pnl_pct'], already_percent=True)})"
                )
    return "\n".join(lines)


def format_server_summary(book: ServerBook) -> str:
    lines = [
        f"**Server paper PnL** **{fmt.money(book.total)}**",
        f"Realized {fmt.money(book.realized)} · Unrealized {fmt.money(book.unrealized)}",
        f"Traders `{len(book.traders)}` · Open positions `{len(book.open_positions)}`",
        "",
    ]
    lines.append(format_leaderboard(book, limit=10))
    return "\n".join(lines)


def format_positions(positions: list[PositionView], *, title: str = "Positions") -> str:
    if not positions:
        return "No open positions."
    lines = [f"**{title}**"]
    for p in positions:
        lines.append(
            f"#{p.id} <@{p.user_id}> {p.side} `{p.symbol}` x{p.qty} @ {fmt.number(p.entry)} → "
            f"{fmt.number(p.last)} ({fmt.money(p.unrealized_dollars)} / "
            f"{fmt.pct(p.unrealized_pct, already_percent=True)})"
        )
    return "\n".join(lines)
