from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from typing import Any

import yfinance as yf

from app import format as fmt

# ISO 4217 codes we accept for FX pair inference (blocks APPLES→APP/LES etc.).
FX_CURRENCIES = {
    "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD", "CNY", "HKD",
    "SGD", "SEK", "NOK", "DKK", "MXN", "ZAR", "INR", "KRW", "BRL", "TRY",
    "PLN", "THB", "TWD", "ILS", "AED", "SAR", "RUB",
}

# Aliases people type in chat → Yahoo symbol (tickers + common company names).
ALIASES: dict[str, str] = {
    "SPX": "^GSPC",
    "SP500": "^GSPC",
    "S&P": "^GSPC",
    "S&P500": "^GSPC",
    "NDX": "^NDX",
    "NASDAQ": "^IXIC",
    "COMP": "^IXIC",
    "DJI": "^DJI",
    "DJIA": "^DJI",
    "DOW": "^DJI",
    "RUT": "^RUT",
    "RUSSELL": "^RUT",
    "VIX": "^VIX",
    "TNX": "^TNX",
    "US10Y": "^TNX",
    "10Y": "^TNX",
    "US2Y": "^IRX",
    "2Y": "^IRX",
    "US30Y": "^TYX",
    "30Y": "^TYX",
    "BTC": "BTC-USD",
    "BITCOIN": "BTC-USD",
    "ETH": "ETH-USD",
    "ETHEREUM": "ETH-USD",
    "SOL": "SOL-USD",
    "XRP": "XRP-USD",
    "DOGE": "DOGE-USD",
    "GOLD": "GC=F",
    "SILVER": "SI=F",
    "OIL": "CL=F",
    "CRUDE": "CL=F",
    "WTI": "CL=F",
    "BRENT": "BZ=F",
    "NATGAS": "NG=F",
    "NG": "NG=F",
    "COPPER": "HG=F",
    "ES": "ES=F",
    "NQ": "NQ=F",
    "YM": "YM=F",
    "RTY": "RTY=F",
    "ZB": "ZB=F",
    "ZN": "ZN=F",
    "ZF": "ZF=F",
    "ZT": "ZT=F",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "JPY=X",
    "JPY": "JPY=X",
    "USDCHF": "CHF=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "CAD=X",
    "NZDUSD": "NZDUSD=X",
    "EUR": "EURUSD=X",
    "GBP": "GBPUSD=X",
    "DXY": "DX-Y.NYB",
    "DOLLAR": "DX-Y.NYB",
    # Company / product names people say in NL
    "APPLE": "AAPL",
    "APPLES": "AAPL",
    "GOOGLE": "GOOGL",
    "GOOG": "GOOGL",
    "ALPHABET": "GOOGL",
    "MICROSOFT": "MSFT",
    "AMAZON": "AMZN",
    "META": "META",
    "FACEBOOK": "META",
    "NVIDIA": "NVDA",
    "TESLA": "TSLA",
    "NETFLIX": "NFLX",
    "COSTCO": "COST",
    "WALMART": "WMT",
    "DISNEY": "DIS",
    "COCA-COLA": "KO",
    "COCACOLA": "KO",
    "COKE": "KO",
    "INTEL": "INTC",
    "AMD": "AMD",
    "UBER": "UBER",
    "AIRBNB": "ABNB",
    "SHOPIFY": "SHOP",
    "SALESFORCE": "CRM",
    "ORACLE": "ORCL",
    "IBM": "IBM",
    "JPMORGAN": "JPM",
    "JPM": "JPM",
    "GOLDMAN": "GS",
    "BERKSHIRE": "BRK-B",
    "EXXON": "XOM",
    "CHEVRON": "CVX",
    "BOEING": "BA",
    "STARBUCKS": "SBUX",
    "NIKE": "NKE",
    "VISA": "V",
    "MASTERCARD": "MA",
    "PAYPAL": "PYPL",
    "SQUARE": "XYZ",
    "BLOCK": "XYZ",
    "SNAP": "SNAP",
    "TWITTER": "X",
    "SPOTIFY": "SPOT",
    "PALANTIR": "PLTR",
    "SNOWFLAKE": "SNOW",
    "CLOUDFLARE": "NET",
    "ROBINHOOD": "HOOD",
    "COINBASE": "COIN",
    "MICROSTRATEGY": "MSTR",
    "STRATEGY": "MSTR",
}

FX_PAIR = re.compile(r"^([A-Z]{3})[\/\-]?([A-Z]{3})$")
CRYPTO_SUFFIX = re.compile(r"^([A-Z0-9]{2,12})[\-/]?(USD|USDT|BTC|ETH)$")
FUTURE_SUFFIX = re.compile(r"^([A-Z0-9]{1,5})=F$")
INDEX_CARET = re.compile(r"^\^[A-Z0-9.\-]+$")
OCC = re.compile(
    r"^([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$"
)
# AAPL 275C 11/16/26  or  AAPL 275 Call Nov 16 2026
OPTION_SHORTHAND = re.compile(
    r"""
    ^\s*
    (?P<root>[A-Za-z.\-]{1,8})
    \s+
    (?P<strike>\d+(?:\.\d+)?)
    \s*
    (?:(?P<side>[CcPp])|(?P<side_word>call|put))
    (?:\s+|/)
    (?:
        (?P<m1>\d{1,2})[/-](?P<d1>\d{1,2})[/-](?P<y1>\d{2,4})
      | (?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*
        \s+(?P<d2>\d{1,2})(?:st|nd|rd|th)?
        (?:\s*,?\s*(?P<y2>\d{2,4}))?
    )
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
TICKER_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?:\$)?([A-Za-z]{1,6}(?:[.\-][A-Za-z0-9]{1,6})?|\^[A-Z0-9.\-]{1,12}|[A-Z]{3}/[A-Z]{3}|[A-Z0-9]{1,10}=F|[A-Z]{2,10}-USD)(?![A-Za-z0-9])"
)

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


@dataclass
class Security:
    symbol: str
    yahoo: str
    quote_type: str
    name: str
    currency: str | None = None
    exchange: str | None = None
    last: float | None = None
    previous_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    volume: float | None = None
    avg_volume: float | None = None
    market_cap: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    yield_: float | None = None
    beta: float | None = None
    year_high: float | None = None
    year_low: float | None = None
    sector: str | None = None
    industry: str | None = None
    website: str | None = None
    summary: str | None = None
    short_percent: float | None = None
    days_to_cover: float | None = None
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    avg_volume_10d: float | None = None
    post_market: float | None = None
    pre_market: float | None = None
    open_interest: float | None = None
    strike: float | None = None
    expiry: str | None = None
    option_side: str | None = None
    underlying: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def asset_label(self) -> str:
        return fmt.ASSET_LABELS.get(self.quote_type.upper(), self.quote_type.title() or "Security")

    @property
    def spread(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2.0

    @property
    def has_book(self) -> bool:
        return self.bid is not None or self.ask is not None

    @property
    def is_equity_like(self) -> bool:
        return self.quote_type.upper() in {"EQUITY", "ETF", "MUTUALFUND"}

    @property
    def is_fx(self) -> bool:
        return self.quote_type.upper() == "CURRENCY"

    @property
    def is_crypto(self) -> bool:
        return self.quote_type.upper() == "CRYPTOCURRENCY"

    @property
    def is_future(self) -> bool:
        return self.quote_type.upper() == "FUTURE"

    @property
    def is_option(self) -> bool:
        return self.quote_type.upper() == "OPTION"

    @property
    def is_index(self) -> bool:
        return self.quote_type.upper() == "INDEX"

    @property
    def is_rate_like(self) -> bool:
        return self.yahoo in {"^TNX", "^IRX", "^FVX", "^TYX"} or "bond" in (self.name or "").lower()


def normalize_symbol(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        raise ValueError("Empty symbol")

    # Option shorthand before uppercasing destroys words.
    option = OPTION_SHORTHAND.match(text)
    if option:
        return _occ_from_shorthand(option)

    cleaned = text.upper().replace("$", "").strip()
    cleaned = cleaned.replace(" ", "")

    if cleaned in ALIASES:
        return ALIASES[cleaned]

    if OCC.match(cleaned):
        return cleaned

    if INDEX_CARET.match(cleaned) or FUTURE_SUFFIX.match(cleaned):
        return cleaned

    if cleaned.endswith("=X") or cleaned.endswith("-USD") or cleaned.endswith("-USDT"):
        return cleaned

    fx = FX_PAIR.match(cleaned.replace("-", "/").replace("=", "/"))
    if fx:
        base, quote = fx.group(1), fx.group(2)
        # Only treat as FX when both legs are real currency codes.
        # Otherwise APPLES / VOLUME / etc. become junk pairs like APPLES=X.
        if base in FX_CURRENCIES and quote in FX_CURRENCIES and base != quote:
            if base == "USD":
                special = {
                    "JPY": "JPY=X",
                    "CHF": "CHF=X",
                    "CAD": "CAD=X",
                    "CNY": "CNY=X",
                    "HKD": "HKD=X",
                }
                return special.get(quote, f"{base}{quote}=X")
            return f"{base}{quote}=X"

    crypto = CRYPTO_SUFFIX.match(cleaned.replace("/", "-"))
    if crypto:
        coin, quote = crypto.group(1), crypto.group(2)
        if quote == "USDT":
            return f"{coin}-USD"
        return f"{coin}-{quote}"

    # BRK.B → BRK-B
    if "." in cleaned and cleaned.count(".") == 1:
        left, right = cleaned.split(".")
        if len(right) <= 2:
            cleaned = f"{left}-{right}"

    return cleaned


def _occ_from_shorthand(match: re.Match[str]) -> str:
    root = match.group("root").upper().replace(".", "-")
    strike = float(match.group("strike"))
    side_letter = (match.group("side") or match.group("side_word") or "C")[0].upper()
    if match.group("m1"):
        month = int(match.group("m1"))
        day = int(match.group("d1"))
        year = int(match.group("y1"))
    else:
        month = MONTHS[match.group("mon")[:3].upper()]
        day = int(match.group("d2"))
        year = int(match.group("y2") or date.today().year)
    if year < 100:
        year += 2000
    strike_int = int(round(strike * 1000))
    return f"{root}{year % 100:02d}{month:02d}{day:02d}{side_letter}{strike_int:08d}"


def extract_tickers(text: str, limit: int = 3) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    # Prefer $TICKER mentions first.
    for match in re.finditer(r"\$([A-Za-z][A-Za-z0-9.\-]{0,15})", text):
        try:
            symbol = normalize_symbol(match.group(1))
        except ValueError:
            continue
        if symbol not in seen:
            seen.add(symbol)
            found.append(symbol)
        if len(found) >= limit:
            return found
    # Bare ticker-only messages.
    stripped = text.strip()
    if re.fullmatch(r"[\$]?[A-Za-z^][A-Za-z0-9.\-=/]{0,24}", stripped):
        try:
            symbol = normalize_symbol(stripped)
            return [symbol]
        except ValueError:
            return []
    return found


@lru_cache(maxsize=256)
def resolve_cached(symbol: str) -> Security:
    return resolve(symbol)


def resolve(symbol: str) -> Security:
    yahoo = normalize_symbol(symbol)
    ticker = yf.Ticker(yahoo)
    info: dict[str, Any] = {}
    try:
        info = ticker.info or {}
    except Exception:
        info = {}

    fast: dict[str, Any] = {}
    try:
        fi = ticker.fast_info
        for key in (
            "last_price",
            "previous_close",
            "open",
            "day_high",
            "day_low",
            "year_high",
            "year_low",
            "last_volume",
            "three_month_average_volume",
            "market_cap",
            "currency",
            "exchange",
            "quote_type",
        ):
            try:
                fast[key] = fi[key]
            except Exception:
                pass
    except Exception:
        pass

    last = _first(info.get("regularMarketPrice"), fast.get("last_price"), info.get("previousClose"))
    prev = _first(info.get("regularMarketPreviousClose"), fast.get("previous_close"), info.get("previousClose"))
    change = info.get("regularMarketChange")
    change_pct = info.get("regularMarketChangePercent")
    if change is None and last is not None and prev not in (None, 0):
        change = last - prev
    if change_pct is None and change is not None and prev not in (None, 0):
        change_pct = (change / prev) * 100

    quote_type = str(
        info.get("quoteType")
        or fast.get("quote_type")
        or _guess_type(yahoo)
    ).upper()
    name = (
        info.get("shortName")
        or info.get("longName")
        or info.get("displayName")
        or yahoo
    )

    expiry = None
    option_side = None
    strike = info.get("strike")
    underlying = info.get("underlyingSymbol")
    occ = OCC.match(yahoo)
    if occ:
        quote_type = "OPTION"
        yy, mm, dd = int(occ.group(2)), int(occ.group(3)), int(occ.group(4))
        expiry = date(2000 + yy, mm, dd).isoformat()
        option_side = "Call" if occ.group(5) == "C" else "Put"
        strike = strike or int(occ.group(6)) / 1000
        underlying = underlying or occ.group(1)

    if not last and not name:
        raise ValueError(f"No quote found for `{symbol}`")
    # Junk Yahoo symbols (e.g. old APPLES=X) often return a shell with no tradeable quote.
    if last is None and info.get("bid") is None and info.get("ask") is None:
        raise ValueError(f"No tradeable quote for `{yahoo}`")

    return Security(
        symbol=yahoo,
        yahoo=yahoo,
        quote_type=quote_type,
        name=str(name),
        currency=_first(info.get("currency"), fast.get("currency")),
        exchange=_first(info.get("fullExchangeName"), info.get("exchange"), fast.get("exchange")),
        last=_float(last),
        previous_close=_float(prev),
        change=_float(change),
        change_pct=_float(change_pct),
        open=_float(_first(info.get("regularMarketOpen"), fast.get("open"), info.get("open"))),
        day_high=_float(_first(info.get("regularMarketDayHigh"), fast.get("day_high"), info.get("dayHigh"))),
        day_low=_float(_first(info.get("regularMarketDayLow"), fast.get("day_low"), info.get("dayLow"))),
        volume=_float(_first(info.get("regularMarketVolume"), fast.get("last_volume"), info.get("volume"))),
        avg_volume=_float(_first(info.get("averageVolume"), fast.get("three_month_average_volume"))),
        market_cap=_float(_first(info.get("marketCap"), fast.get("market_cap"))),
        trailing_pe=_float(info.get("trailingPE")),
        forward_pe=_float(info.get("forwardPE")),
        yield_=_dividend_yield_fraction(info, last=_float(last)),
        beta=_float(info.get("beta")),
        year_high=_float(_first(info.get("fiftyTwoWeekHigh"), fast.get("year_high"))),
        year_low=_float(_first(info.get("fiftyTwoWeekLow"), fast.get("year_low"))),
        sector=info.get("sector"),
        industry=info.get("industry"),
        website=info.get("website"),
        summary=info.get("longBusinessSummary") or info.get("description"),
        # Yahoo shortPercentOfFloat is a fraction (0.01 = 1%).
        short_percent=_float(info.get("shortPercentOfFloat")),
        days_to_cover=_float(info.get("shortRatio")),
        bid=_float(info.get("bid")),
        ask=_float(info.get("ask")),
        bid_size=_float(info.get("bidSize")),
        ask_size=_float(info.get("askSize")),
        avg_volume_10d=_float(
            _first(info.get("averageDailyVolume10Day"), info.get("averageVolume10days"))
        ),
        post_market=_float(info.get("postMarketPrice")),
        pre_market=_float(info.get("preMarketPrice")),
        open_interest=_float(info.get("openInterest")),
        strike=_float(strike),
        expiry=expiry or _as_iso(info.get("expireDate")),
        option_side=option_side,
        underlying=underlying,
        raw=info,
    )


def invalidate_cache(symbol: str | None = None) -> None:
    if symbol is None:
        resolve_cached.cache_clear()
    else:
        resolve_cached.cache_clear()


def _guess_type(yahoo: str) -> str:
    if OCC.match(yahoo):
        return "OPTION"
    if yahoo.endswith("=X"):
        return "CURRENCY"
    if yahoo.endswith("-USD") or yahoo.endswith("-USDT"):
        return "CRYPTOCURRENCY"
    if yahoo.endswith("=F"):
        return "FUTURE"
    if yahoo.startswith("^"):
        return "INDEX"
    return "EQUITY"


def _first(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, float) and value != value:  # NaN
            continue
        return value
    return None


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _dividend_yield_fraction(info: dict[str, Any], *, last: float | None = None) -> float | None:
    """Return dividend yield as a fraction (0.003 = 0.3%).

    Yahoo is inconsistent:
    - ``trailingAnnualDividendYield`` → true fraction (0.00299)
    - ``dividendYield`` → percent *points* (0.3 meaning 0.3%, 5.0 meaning 5%)
    - ETF ``yield`` → usually a fraction
    """
    trailing = _float(info.get("trailingAnnualDividendYield"))
    if trailing is not None and 0 <= trailing < 1:
        return trailing

    # Prefer computing from cash dividend / price when we can.
    rate = _float(
        _first(info.get("trailingAnnualDividendRate"), info.get("dividendRate"))
    )
    price = _float(
        _first(last, info.get("currentPrice"), info.get("regularMarketPrice"))
    )
    if rate is not None and price and price > 0:
        return rate / price

    dy = _float(info.get("dividendYield"))
    if dy is not None and dy >= 0:
        # Yahoo dividendYield is percent points (0.3 → 0.3%, not 30%).
        return dy / 100.0

    y = _float(info.get("yield"))
    if y is None or y < 0:
        return None
    # ETF yield is usually a fraction; if it's clearly percent points, scale it.
    if y > 1.0:
        return y / 100.0
    return y


def _as_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)) and value > 1_000_000_000:
        return datetime.utcfromtimestamp(value).date().isoformat()
    text = str(value)
    return text[:10] if text else None
