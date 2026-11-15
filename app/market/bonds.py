from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.request import Request, urlopen

import aiohttp

from app import format as fmt

TRACE_URL = (
    "https://services-dynarep.ddwa.finra.org/public/reporting/v2/data/group/"
    "FixedIncomeMarket/name"
)
TRACE_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
OPENFIGI_SEARCH = "https://api.openfigi.com/v3/search"
OPENFIGI_MAP = "https://api.openfigi.com/v3/mapping"

FRACTIONS = {
    "1/8": 0.125,
    "1/4": 0.25,
    "3/8": 0.375,
    "1/2": 0.5,
    "5/8": 0.625,
    "3/4": 0.75,
    "7/8": 0.875,
}
MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

# IHRT 8 3/8 May 2027  |  IHRT 8.375 05/01/27  |  IHRT 8.375% 5/1/2027  |  … 144A
BOND_QUERY = re.compile(
    r"""
    ^\s*
    (?P<root>[A-Za-z][A-Za-z0-9.\-]{0,9})
    \s+
    (?P<whole>\d{1,2})
    (?:
        \s+(?P<frac>1/8|1/4|3/8|1/2|5/8|3/4|7/8)
      | (?:\.(?P<decimal>\d{1,4}))
    )?
    \s*%?
    \s+
    (?:
        (?P<m1>\d{1,2})[/-](?P<d1>\d{1,2})[/-](?P<y1>\d{2,4})
      | (?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*
        \s+(?P<d2>\d{1,2})(?:st|nd|rd|th)?
        ,?\s+(?P<y2>\d{2,4})
      | (?P<mon_only>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*
        \s+(?P<y3>\d{4}|\d{2})
    )
    # Optional OpenFIGI / TRACE suffixes (144A, JUN, etc.)
    (?:\s+[A-Za-z0-9][\w\-/\.]{0,20})*
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
CUSIP_RE = re.compile(r"^[0-9A-Z]{9}$", re.IGNORECASE)
ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$", re.IGNORECASE)
FINRA_SYM = re.compile(r"^[A-Z]{1,6}\d{5,}$", re.IGNORECASE)

CA_FIELDS = [
    "finraSecurityIdentifier",
    "cusip",
    "issueSymbolIdentifier",
    "issuerName",
    "productSubTypeCode",
    "couponRate",
    "couponType",
    "maturityDate",
    "isPerpetual",
    "isCallable",
    "nextCallDate",
    "isConvertible",
    "is144A",
    "industryGroup",
    "traceGradeCode",
    "moodysRating",
    "moodyRatingDate",
    "standardAndPoorsRating",
    "standardAndPoorsRatingDate",
    "lastSalePrice",
    "lastSaleYield",
    "lastTradeDate",
    "priceChangeNumber",
    "priceChangePercent",
]


@dataclass
class BondQuote:
    display: str
    issuer: str
    cusip: str | None = None
    figi: str | None = None
    isin: str | None = None
    finra_symbol: str | None = None
    coupon: float | None = None
    maturity: str | None = None
    last_price: float | None = None
    last_yield: float | None = None
    last_trade_date: str | None = None
    price_change: float | None = None
    price_change_pct: float | None = None
    callable: bool | None = None
    next_call: str | None = None
    convertible: bool | None = None
    is_144a: bool | None = None
    moodys: str | None = None
    sp: str | None = None
    grade: str | None = None  # H = high yield, I = IG
    industry: str | None = None
    coupon_type: str | None = None
    security_description: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def yahoo(self) -> str:
        # Use a stable chat key: prefer issuer ticker, else CUSIP.
        return self.display or self.cusip or self.finra_symbol or "BOND"

    @property
    def quote_type(self) -> str:
        return "BOND"

    @property
    def asset_label(self) -> str:
        return "Corporate Bond"

    @property
    def change(self) -> float | None:
        return self.price_change

    @property
    def change_pct(self) -> float | None:
        return self.price_change_pct

    @property
    def last(self) -> float | None:
        return self.last_price

    @property
    def currency(self) -> str:
        return "USD"

    @property
    def name(self) -> str:
        return self.issuer or self.display


def looks_like_bond_query(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if CUSIP_RE.match(cleaned) or ISIN_RE.match(cleaned):
        return True
    if FINRA_SYM.match(cleaned) and any(ch.isdigit() for ch in cleaned):
        # IHRT4830027 style — not a plain equity ticker
        root = re.match(r"^[A-Za-z]+", cleaned)
        if root and len(cleaned) > len(root.group(0)) + 3:
            return True
    return BOND_QUERY.match(cleaned) is not None


def parse_bond_query(text: str) -> dict[str, Any]:
    cleaned = " ".join((text or "").strip().split())
    if CUSIP_RE.match(cleaned):
        return {"cusip": cleaned.upper()}
    if ISIN_RE.match(cleaned):
        return {"isin": cleaned.upper()}
    if FINRA_SYM.match(cleaned):
        return {"finra_symbol": cleaned.upper()}

    match = BOND_QUERY.match(cleaned)
    if not match:
        raise ValueError(
            "Could not parse bond. Try `IHRT 8 3/8 May 2027`, `IHRT 8.375 05/01/27`, or a CUSIP."
        )

    whole = int(match.group("whole"))
    if match.group("frac"):
        coupon = whole + FRACTIONS[match.group("frac")]
    elif match.group("decimal"):
        coupon = float(f"{whole}.{match.group('decimal')}")
    else:
        coupon = float(whole)

    day_known = True
    if match.group("m1"):
        month = int(match.group("m1"))
        day = int(match.group("d1"))
        year = int(match.group("y1"))
    elif match.group("mon"):
        month = MONTHS[match.group("mon")[:3].upper()]
        day = int(match.group("d2"))
        year = int(match.group("y2"))
    else:
        month = MONTHS[match.group("mon_only")[:3].upper()]
        day = 1
        year = int(match.group("y3"))
        day_known = False
    if year < 100:
        year += 2000

    maturity = date(year, month, day)
    start = date(year, month, 1)
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month + 1, 1).fromordinal(date(year, month + 1, 1).toordinal() - 1)

    return {
        "root": match.group("root").upper().replace(".", "-"),
        "coupon": coupon,
        "maturity": maturity.isoformat() if day_known else None,
        "maturity_month": f"{year:04d}-{month:02d}",
        "maturity_start": start.isoformat(),
        "maturity_end": end.isoformat(),
        "query": cleaned,
        "day_known": day_known,
    }


def _http_json(method: str, url: str, payload: Any | None = None, headers: dict | None = None) -> Any:
    body = None if payload is None else json.dumps(payload).encode()
    req = Request(
        url,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "market-desk/1.0",
            **(headers or {}),
        },
    )
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def openfigi_resolve(parsed: dict[str, Any]) -> dict[str, Any]:
    if parsed.get("cusip"):
        rows = _http_json(
            "POST",
            OPENFIGI_MAP,
            [{"idType": "ID_CUSIP", "idValue": parsed["cusip"]}],
        )
        data = (rows[0] or {}).get("data") or []
        if not data:
            raise ValueError(f"OpenFIGI found no bond for CUSIP {parsed['cusip']}")
        return data[0]

    if parsed.get("isin"):
        rows = _http_json(
            "POST",
            OPENFIGI_MAP,
            [{"idType": "ID_ISIN", "idValue": parsed["isin"]}],
        )
        data = (rows[0] or {}).get("data") or []
        if not data:
            raise ValueError(f"OpenFIGI found no bond for ISIN {parsed['isin']}")
        return data[0]

    root = parsed["root"]
    coupon = parsed["coupon"]
    maturity_key = parsed.get("maturity") or parsed.get("maturity_end") or ""
    mapping = _http_json(
        "POST",
        OPENFIGI_MAP,
        [
            {
                "idType": "BASE_TICKER",
                "idValue": root,
                "securityType2": "Corp",
                "coupon": [coupon - 0.05, coupon + 0.05],
                "maturity": [parsed["maturity_start"], parsed["maturity_end"]],
            }
        ],
    )
    data = (mapping[0] or {}).get("data") or []
    if data:
        return _pick_best(data, coupon, maturity_key)

    # Free-text fallback — matches "IHRT 8 3/8 05/01/27" descriptions.
    search = _http_json(
        "POST",
        OPENFIGI_SEARCH,
        {
            "query": parsed.get("query") or f"{root} {coupon} {maturity_key}",
            "marketSecDes": "Corp",
        },
    )
    data = search.get("data") or []
    if not data:
        raise ValueError(
            f"No corporate bond found for {root} {coupon} "
            f"{parsed.get('maturity') or parsed.get('maturity_month')}"
        )
    return _pick_best(data, coupon, maturity_key)


def _pick_best(rows: list[dict[str, Any]], coupon: float, maturity: str) -> dict[str, Any]:
    def score(row: dict[str, Any]) -> tuple:
        desc = (row.get("securityDescription") or row.get("ticker") or "").upper()
        # Prefer TRACE listings and exact-looking descriptions.
        return (
            0 if row.get("exchCode") == "TRACE" else 1,
            0 if maturity[2:4] in desc or maturity[:4] in desc else 1,
            0 if str(coupon) in desc or "3/8" in desc.lower() else 1,
        )

    return sorted(rows, key=score)[0]


async def trace_by_cusip(cusip: str) -> dict[str, Any] | None:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{TRACE_URL}/CorporateAndAgencySecurities",
            headers={"User-Agent": TRACE_UA, "Accept": "application/json"},
        ) as seed:
            await seed.read()
            token = None
            for cookie in session.cookie_jar:
                if cookie.key == "XSRF-TOKEN":
                    token = cookie.value
        if not token:
            raise RuntimeError("FINRA TRACE did not issue an XSRF token")

        payload = {
            "fields": CA_FIELDS,
            "domainFilters": [{"fieldName": "cusip", "values": [cusip.upper()]}],
            "offset": 0,
            "limit": 5,
        }
        async with session.post(
            f"{TRACE_URL}/corporateAndAgencySecurities",
            json=payload,
            headers={
                "User-Agent": TRACE_UA,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Origin": "https://www.finra.org",
                "Referer": "https://www.finra.org/finra-data/fixed-income/corp-and-agency/trade",
                "X-XSRF-TOKEN": token,
            },
        ) as resp:
            body = await resp.json(content_type=None)
        if body.get("status") != "success":
            raise RuntimeError(body.get("statusMessage") or "TRACE query failed")
        data = (body.get("returnBody") or {}).get("data")
        if isinstance(data, str):
            data = json.loads(data) if data.strip() else []
        rows = data if isinstance(data, list) else []
        return rows[0] if rows else None


async def trace_by_symbol(symbol: str) -> dict[str, Any] | None:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{TRACE_URL}/CorporateAndAgencySecurities",
            headers={"User-Agent": TRACE_UA, "Accept": "application/json"},
        ) as seed:
            await seed.read()
            token = None
            for cookie in session.cookie_jar:
                if cookie.key == "XSRF-TOKEN":
                    token = cookie.value
        payload = {
            "fields": CA_FIELDS,
            "domainFilters": [
                {"fieldName": "issueSymbolIdentifier", "values": [symbol.upper()]}
            ],
            "offset": 0,
            "limit": 5,
        }
        async with session.post(
            f"{TRACE_URL}/corporateAndAgencySecurities",
            json=payload,
            headers={
                "User-Agent": TRACE_UA,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Origin": "https://www.finra.org",
                "Referer": "https://www.finra.org/finra-data/fixed-income/corp-and-agency/trade",
                "X-XSRF-TOKEN": token or "",
            },
        ) as resp:
            body = await resp.json(content_type=None)
        data = (body.get("returnBody") or {}).get("data")
        if isinstance(data, str):
            data = json.loads(data) if data.strip() else []
        rows = data if isinstance(data, list) else []
        return rows[0] if rows else None


async def resolve_bond(text: str) -> BondQuote:
    parsed = parse_bond_query(text)
    figi_row: dict[str, Any] = {}
    cusip = parsed.get("cusip")
    finra_symbol = parsed.get("finra_symbol")

    if not cusip and not finra_symbol:
        figi_row = openfigi_resolve(parsed)
        display = figi_row.get("ticker") or figi_row.get("securityDescription") or text
        # OpenFIGI rarely returns CUSIP; price comes from TRACE by coupon + maturity month.
        maturity_for_trace = parsed.get("maturity")
        if not maturity_for_trace and figi_row.get("ticker"):
            # Pull MM/DD/YY out of "IHRT 8.375 05/01/27"
            m = re.search(r"(\d{2})/(\d{2})/(\d{2,4})\s*$", str(figi_row["ticker"]))
            if m:
                yy = int(m.group(3))
                if yy < 100:
                    yy += 2000
                maturity_for_trace = f"{yy:04d}-{m.group(1)}-{m.group(2)}"
        trace = await _trace_search(
            issuer_hint=parsed.get("root") or "",
            coupon=parsed.get("coupon"),
            maturity=maturity_for_trace,
            maturity_start=parsed.get("maturity_start"),
            maturity_end=parsed.get("maturity_end"),
        )
        if not trace:
            return BondQuote(
                display=str(display),
                issuer=str(figi_row.get("name") or parsed.get("root") or ""),
                figi=figi_row.get("figi"),
                coupon=parsed.get("coupon"),
                maturity=maturity_for_trace or parsed.get("maturity"),
                security_description=figi_row.get("securityDescription"),
                raw={"openfigi": figi_row},
            )
    elif cusip:
        trace = await trace_by_cusip(cusip)
        if not trace:
            raise ValueError(f"TRACE has no corporate/agency bond for CUSIP {cusip}")
    else:
        trace = await trace_by_symbol(finra_symbol)  # type: ignore[arg-type]
        if not trace:
            raise ValueError(f"TRACE has no bond for symbol {finra_symbol}")

    return _from_trace(trace, figi_row)


async def _trace_search(
    *,
    issuer_hint: str,
    coupon: float | None,
    maturity: str | None,
    maturity_start: str | None = None,
    maturity_end: str | None = None,
) -> dict[str, Any] | None:
    """Find a CA bond by coupon + maturity, then prefer issuer ticker hint."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{TRACE_URL}/CorporateAndAgencySecurities",
            headers={"User-Agent": TRACE_UA, "Accept": "application/json"},
        ) as seed:
            await seed.read()
            token = None
            for cookie in session.cookie_jar:
                if cookie.key == "XSRF-TOKEN":
                    token = cookie.value

        headers = {
            "User-Agent": TRACE_UA,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://www.finra.org",
            "Referer": "https://www.finra.org/finra-data/fixed-income/corp-and-agency/trade",
            "X-XSRF-TOKEN": token or "",
        }

        async def run(payload: dict[str, Any]) -> list[dict[str, Any]]:
            async with session.post(
                f"{TRACE_URL}/corporateAndAgencySecurities",
                json=payload,
                headers=headers,
            ) as resp:
                body = await resp.json(content_type=None)
            if body.get("status") != "success":
                return []
            data = (body.get("returnBody") or {}).get("data")
            if isinstance(data, str):
                data = json.loads(data) if data.strip() else []
            return data if isinstance(data, list) else []

        compare_filters: list[dict[str, Any]] = []
        if coupon is not None:
            compare_filters.append(
                {
                    "fieldName": "couponRate",
                    "compareType": "EQUAL",
                    "fieldValue": coupon,
                }
            )
        if maturity:
            compare_filters.append(
                {
                    "fieldName": "maturityDate",
                    "compareType": "EQUAL",
                    "fieldValue": maturity,
                }
            )
        elif maturity_start and maturity_end:
            compare_filters.extend(
                [
                    {
                        "fieldName": "maturityDate",
                        "compareType": "GREATER_THAN_OR_EQUAL",
                        "fieldValue": maturity_start,
                    },
                    {
                        "fieldName": "maturityDate",
                        "compareType": "LESS_THAN_OR_EQUAL",
                        "fieldValue": maturity_end,
                    },
                ]
            )

        rows = await run(
            {
                "fields": CA_FIELDS,
                "compareFilters": compare_filters,
                "offset": 0,
                "limit": 100,
            }
        )
        if not rows and coupon is not None:
            # Looser coupon band if exact equality misses float formatting.
            rows = await run(
                {
                    "fields": CA_FIELDS,
                    "compareFilters": [
                        {
                            "fieldName": "couponRate",
                            "compareType": "GREATER_THAN_OR_EQUAL",
                            "fieldValue": round(coupon - 0.01, 4),
                        },
                        {
                            "fieldName": "couponRate",
                            "compareType": "LESS_THAN_OR_EQUAL",
                            "fieldValue": round(coupon + 0.01, 4),
                        },
                        *(
                            [
                                {
                                    "fieldName": "maturityDate",
                                    "compareType": "EQUAL",
                                    "fieldValue": maturity,
                                }
                            ]
                            if maturity
                            else [
                                {
                                    "fieldName": "maturityDate",
                                    "compareType": "GREATER_THAN_OR_EQUAL",
                                    "fieldValue": maturity_start,
                                },
                                {
                                    "fieldName": "maturityDate",
                                    "compareType": "LESS_THAN_OR_EQUAL",
                                    "fieldValue": maturity_end,
                                },
                            ]
                            if maturity_start and maturity_end
                            else []
                        ),
                    ],
                    "offset": 0,
                    "limit": 100,
                }
            )

        if not rows:
            return None

        hint = (issuer_hint or "").upper()
        ranked = sorted(
            rows,
            key=lambda r: (
                0 if str(r.get("issueSymbolIdentifier") or "").upper().startswith(hint) else 1,
                0 if hint and hint in str(r.get("issuerName") or "").upper() else 1,
                abs(float(r.get("couponRate") or 0) - (coupon or 0)),
            ),
        )
        return ranked[0]


def _from_trace(trace: dict[str, Any], figi_row: dict[str, Any] | None = None) -> BondQuote:
    figi_row = figi_row or {}
    coupon = _f(trace.get("couponRate"))
    maturity = trace.get("maturityDate")
    root = re.match(r"^[A-Z]+", str(trace.get("issueSymbolIdentifier") or ""))
    display = figi_row.get("ticker") or figi_row.get("securityDescription")
    if not display and coupon and maturity:
        stamp = str(maturity)[5:7] + "/" + str(maturity)[8:10] + "/" + str(maturity)[2:4]
        prefix = root.group(0) if root else "BOND"
        display = f"{prefix} {coupon:g} {stamp}"
    grade = trace.get("traceGradeCode")
    return BondQuote(
        display=str(display or trace.get("issueSymbolIdentifier") or trace.get("cusip")),
        issuer=str(trace.get("issuerName") or figi_row.get("name") or ""),
        cusip=trace.get("cusip"),
        figi=figi_row.get("figi"),
        finra_symbol=trace.get("issueSymbolIdentifier"),
        coupon=coupon,
        maturity=str(maturity) if maturity else None,
        last_price=_f(trace.get("lastSalePrice")),
        last_yield=_f(trace.get("lastSaleYield")),
        last_trade_date=str(trace.get("lastTradeDate") or "") or None,
        price_change=_f(trace.get("priceChangeNumber")),
        price_change_pct=_f(trace.get("priceChangePercent")),
        callable=_yn(trace.get("isCallable")),
        next_call=str(trace.get("nextCallDate") or "") or None,
        convertible=_yn(trace.get("isConvertible")),
        is_144a=_yn(trace.get("is144A")),
        moodys=trace.get("moodysRating"),
        sp=trace.get("standardAndPoorsRating"),
        grade="HY" if grade == "H" else "IG" if grade == "I" else grade,
        industry=trace.get("industryGroup"),
        coupon_type=trace.get("couponType"),
        security_description=figi_row.get("securityDescription"),
        raw={"trace": trace, "openfigi": figi_row},
    )


def bond_card_text(bond: BondQuote) -> str:
    arrow = "▲" if (bond.price_change or 0) > 0 else "▼" if (bond.price_change or 0) < 0 else "•"
    lines = [
        f"# {bond.display} · Bond",
        f"**{bond.issuer}**",
    ]
    if bond.last_price is not None:
        lines.append(
            f"{arrow} `{fmt.number(bond.last_price)}` "
            f"{fmt.signed(bond.price_change)} ({fmt.pct(bond.price_change_pct, already_percent=True)}) "
            f"· YTM `{fmt.number(bond.last_yield)}%`"
        )
    else:
        lines.append("_No recent TRACE print — identity only._")

    meta = [
        f"Coupon `{fmt.number(bond.coupon, 3)}%`" if bond.coupon is not None else None,
        f"Maturity `{bond.maturity}`" if bond.maturity else None,
        f"CUSIP `{bond.cusip}`" if bond.cusip else None,
        f"TRACE `{bond.finra_symbol}`" if bond.finra_symbol else None,
    ]
    lines.append(" · ".join(x for x in meta if x))

    extras = [
        f"Last trade `{bond.last_trade_date}`" if bond.last_trade_date else None,
        f"Moody's `{bond.moodys}`" if bond.moodys else None,
        f"S&P `{bond.sp}`" if bond.sp else None,
        f"Grade `{bond.grade}`" if bond.grade else None,
        "Callable" if bond.callable else None,
        f"Next call `{bond.next_call}`" if bond.next_call else None,
        "144A" if bond.is_144a else None,
    ]
    cleaned = [x for x in extras if x]
    if cleaned:
        lines.append(" · ".join(cleaned))
    if bond.security_description:
        lines.append(f"_{bond.security_description}_")
    return "\n".join(lines)


def bond_links(bond: BondQuote) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    if bond.cusip:
        links.append(
            (
                "FINRA",
                f"https://www.finra.org/finra-data/fixed-income/bond?cusip={bond.cusip}&bondType=CA",
            )
        )
        links.append(("BondFacts", f"https://bondfacts.finra.org/{bond.cusip}"))
    if bond.finra_symbol:
        links.append(
            (
                "TradingView",
                f"https://www.tradingview.com/symbols/FINRA-{bond.finra_symbol}/",
            )
        )
        links.append(
            (
                "Trades",
                f"https://www.finra.org/finra-data/fixed-income/trade-history?symbol={bond.finra_symbol}&bondType=CA",
            )
        )
    if bond.figi:
        links.append(("OpenFIGI", f"https://www.openfigi.com/figi/{bond.figi}"))
    return links


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _yn(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).upper() in {"Y", "YES", "TRUE", "1"}
