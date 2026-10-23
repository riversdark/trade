import sys
import time
import json
import urllib.error
import urllib.request
from datetime import date
from dataclasses import dataclass

@dataclass(frozen=True)
class Bar:
    """One day's OHLCV observation for one instrument."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int

type Bars = tuple[Bar, ...]             # ordered oldest first

# one request per symbol -> up to 640 daily OHLCV bars
KLINE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

# one request -> many symbols' Chinese names and latest quotes
QUOTE = "https://qt.gtimg.cn/q="

# Q: what's this for?
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) notes-trade/0.1"}

DEPTH = 10     # rows requested while exploring; endpoint cap is 640
DELAY = 0.35    # Seconds between symbol requests
BATCH = 50      # symbols per quote request
RETRIES = 3

def get(url: str, *, encoding: str = "utf-8") -> str:
    """One GET, retried, so a dropped connection is not a data gap."""
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=HEADERS),
                    timeout=20) as response:
                return response.read().decode(encoding, errors="replace")
        except (urllib.error.URLError, OSError):
            if attempt == RETRIES - 1:
                raise
            time.sleep(DELAY * 2 ** attempt)
    raise AssertionError("unreachable")

def market_code(symbol: str) -> str:
    """A-share symbol -> Tencent's market-prefixed code."""
    if symbol.startswith(("6", "9")):
        return f"sh{symbol}"
    if symbol.startswith(("4", "8")):
        return f"bj{symbol}"
    return f"sz{symbol}"

def parse_bars(payload: str, symbol: str, adjust: str) -> Bars:
    """Decode one fqkline response into market bars, oldest first."""
    code = market_code(symbol)
    rows = json.loads(payload)["data"][code][f"{adjust}day"]
    return tuple(
        Bar(date=date.fromisoformat(row[0]),
            open=float(row[1]),
            high=float(row[3]),
            low=float(row[4]),
            close=float(row[2]),
            volume=int(float(row[5])))
        for row in rows
    )

def fetch_bars(symbol: str, adjust: str) -> Bars:
    """Fetch and parse one symbol's daily bars."""
    span = f"1900-01-01,{date.today().isoformat()}"
    url = f"{KLINE}?param={market_code(symbol)},day,{span},{DEPTH},{adjust}"
    return parse_bars(get(url), symbol, adjust)

def fetch_names(symbols: tuple[str, ...]) -> tuple[str, ...]:
    """Return raw quote responses, one per BATCH symbols."""
    codes = [market_code(symbol) for symbol in symbols]
    responses = []
    for start in range(0, len(codes), BATCH):
        chunk = codes[start:start + BATCH]
        # GBK, not UTF-8: the endpoint is an old one and answers in it.
        responses.append(get(QUOTE + ",".join(chunk), encoding="gbk"))
    return tuple(responses)

def parse_names(responses: tuple[str, ...]) -> dict[str, str]:
    """Decode quote responses into symbol -> name."""
    names: dict[str, str] = {}
    for text in responses:
        for line in text.split(";"):
            fields = line.split("~")
            if len(fields) > 3 and fields[2].isdigit():
                names[fields[2]] = "".join(fields[1].split())
    return names

if __name__ == "__main__":

    match sys.argv[1:]:
        case ["refresh", *symbols]:
            from market import refresh
            refresh(tuple(symbols))
        case _:
            raise SystemExit("usage: python source.py refresh [symbol ...]")
