from app.market.bonds import looks_like_bond_query, parse_bond_query


def test_parse_fraction_month_year():
    parsed = parse_bond_query("IHRT 8 3/8 May 2027")
    assert parsed["root"] == "IHRT"
    assert parsed["coupon"] == 8.375
    assert parsed["day_known"] is False
    assert parsed["maturity_month"] == "2027-05"
    assert parsed["maturity_start"] == "2027-05-01"
    assert parsed["maturity_end"] == "2027-05-31"


def test_parse_decimal_dated():
    parsed = parse_bond_query("IHRT 8.375 05/01/27")
    assert parsed["coupon"] == 8.375
    assert parsed["maturity"] == "2027-05-01"
    assert parsed["day_known"] is True


def test_parse_cusip():
    assert parse_bond_query("45174HBD8") == {"cusip": "45174HBD8"}


def test_looks_like_bond():
    assert looks_like_bond_query("IHRT 8 3/8 May 2027")
    assert looks_like_bond_query("45174HBD8")
    assert not looks_like_bond_query("AAPL")
    assert not looks_like_bond_query("hello world")
