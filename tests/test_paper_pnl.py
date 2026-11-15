from __future__ import annotations

from pathlib import Path

from app.db import Database
from app.services import paper_pnl
from app.services.markit_nl import parse_local


def test_pnl_math() -> None:
    assert paper_pnl.pnl_dollars("long", 100, 110, 2) == 20
    assert paper_pnl.pnl_dollars("short", 100, 90, 2) == 20
    assert abs(paper_pnl.pnl_pct("long", 100, 110) - 10) < 1e-9


def test_paper_close_books_realized(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.db")
    pid = db.paper_open(1, 42, "AAPL", "long", 2, 100.0)
    closed = db.paper_close(pid, 42, exit_price=110.0)
    assert closed is not None
    assert float(closed["pnl_dollars"]) == 20.0
    assert db.paper_list(1, 42) == []
    assert db.paper_realized_by_user(1)[42] == 20.0


def test_nl_paper_buy() -> None:
    intent = parse_local("paper buy 10 AAPL")
    assert intent is not None
    assert intent.action == "paper_buy"
    assert intent.qty == 10
    assert intent.symbol and "AAPL" in intent.symbol.upper()


def test_nl_leaderboard() -> None:
    intent = parse_local("who's winning on the leaderboard")
    assert intent is not None
    assert intent.action == "paper_leaderboard"


def test_nl_server_pnl() -> None:
    intent = parse_local("server pnl")
    assert intent is not None
    assert intent.action == "paper_server"


def test_nl_close_position() -> None:
    intent = parse_local("close position #12")
    assert intent is not None
    assert intent.action == "paper_close"
    assert intent.position_id == 12
