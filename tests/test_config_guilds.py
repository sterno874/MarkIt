from __future__ import annotations

from app.config import _parse_guild_ids


def test_parse_single() -> None:
    assert _parse_guild_ids("123456789012345678") == [123456789012345678]


def test_parse_comma_list() -> None:
    assert _parse_guild_ids("111,222, 333") == [111, 222, 333]


def test_parse_space_list_and_dedupe() -> None:
    assert _parse_guild_ids("111 222 111") == [111, 222]


def test_parse_empty() -> None:
    assert _parse_guild_ids("") == []
    assert _parse_guild_ids("  ,  ") == []
