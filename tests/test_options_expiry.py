from __future__ import annotations

from app.market.statements import options_chain
from app.security import extract_option_contracts, normalize_symbol
from app.services.markit_nl import parse_local


def test_shorthand_snaps_nov21_to_listed_friday() -> None:
    # Nov 21 2026 is Saturday — AAPL lists 2026-11-20 (and 11-23).
    occ = normalize_symbol("AAPL 362.5C 11/21/26")
    assert occ.startswith("AAPL")
    assert "C00362500" in occ
    # Snapped off the Saturday onto a listed expiry (not left as 261121).
    assert "261121" not in occ


def test_extract_option_from_sentence() -> None:
    found = extract_option_contracts("quote the AAPL 360 call Nov 21")
    assert found
    assert found[0].startswith("AAPL")
    assert "C00360000" in found[0]


def test_parse_local_prefers_option_over_equity() -> None:
    intent = parse_local("AAPL 362.5C 11/20/26")
    assert intent is not None
    assert intent.action == "quote"
    assert intent.symbol and intent.symbol.startswith("AAPL26")
    assert intent.expiry == "2026-11-20"


def test_options_chain_uses_requested_expiry() -> None:
    data = options_chain("AAPL", "2026-11-20")
    assert data["expiry"] == "2026-11-20"
    assert "2026-11-20" in data["text"]


def test_bare_iso_expiry_and_options_verb() -> None:
    intent = parse_local("options on AAPL 2026-11-20")
    assert intent is not None
    assert intent.action == "options"
    assert intent.symbol == "AAPL"
    assert intent.expiry == "2026-11-20"


def test_aapl_options_maps_to_options_action() -> None:
    intent = parse_local("AAPL options")
    assert intent is not None
    assert intent.action == "options"
    assert intent.symbol == "AAPL"
