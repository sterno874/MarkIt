from __future__ import annotations

from app.autocomplete import (
    PERIODS,
    POPULAR,
    _dedupe,
    _local_symbol_hits,
    _choice,
)


class _FakeUser:
    id = 42


class _FakeInteraction:
    guild_id = None
    channel_id = None
    user = _FakeUser()


def test_popular_seeded() -> None:
    assert any(sym == "AAPL" for sym, _ in POPULAR)
    assert "6m" in PERIODS


def test_local_hits_offer_typed_and_aliases() -> None:
    hits = _local_symbol_hits("btc", _FakeInteraction())
    values = [h.value.upper() for h in hits]
    assert "BTC" in values
    assert any(h.value.upper() == "BTC" for h in hits)


def test_dedupe_caps_at_25() -> None:
    choices = [_choice(f"S{i}", f"S{i}") for i in range(40)]
    assert len(_dedupe(choices)) == 25
