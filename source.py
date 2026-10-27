import sys
import time
import json
import csv
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from watches import WATCHLIST

# one request per symbol -> up to 640 daily OHLCV bars
KLINE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

# one request -> many symbols' Chinese names and latest quotes
QUOTE = "https://qt.gtimg.cn/q="

# Q: what's this for?
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) notes-trade/0.1"}

DEPTH = 640     # rows requested while exploring; endpoint cap is 640
DELAY = 0.35    # Seconds between symbol requests
BATCH = 50      # symbols per quote request
RETRIES = 3

def market_code(symbol: str) -> str:
    """A-share symbol -> Tencent's market-prefixed code."""
    if symbol.startswith(("6", "9")):
        return f"sh{symbol}"
    if symbol.startswith(("4", "8")):
        return f"bj{symbol}"
    return f"sz{symbol}"

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

STORE = Path.home() / "git" / "notes" / "projects" / "trade" / "bars"
SERIES = ("raw", "qfq")
ADJUST = {"raw": "", "qfq": "qfq"}

def write_bars(symbol: str, adjust: str, path: Path) -> None:
    """Fetch, normalize, and store one complete daily series."""
    span = f"1900-01-01,{date.today().isoformat()}"
    code = market_code(symbol)
    url = f"{KLINE}?param={code},day,{span},{DEPTH},{adjust}"
    rows = json.loads(get(url))["data"][code][f"{adjust}day"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("date", "open", "high", "low", "close", "volume"))
        writer.writerows(
            (row[0], row[1], row[3], row[4], row[2], int(float(row[5])))
            for row in rows
        )
    print(f"{adjust or 'raw':>3} {symbol} {len(rows):>4} bars "
          f"{rows[0][0]} .. {rows[-1][0]}")

def write_names(symbols: tuple[str, ...], path: Path) -> None:
    """Fetch, merge, and store names for the selected symbols."""
    codes = [market_code(symbol) for symbol in symbols]
    fetched: dict[str, str] = {}
    for start in range(0, len(codes), BATCH):
        chunk = codes[start:start + BATCH]
        text = get(QUOTE + ",".join(chunk), encoding="gbk")
        for line in text.split(";"):
            fields = line.split("~")
            if len(fields) > 3 and fields[2].isdigit():
                fetched[fields[2]] = "".join(fields[1].split())

    stored: dict[str, str] = {}
    if path.exists():
        with open(path, newline="") as handle:
            stored = {row["symbol"]: row["name"]
                      for row in csv.DictReader(handle)}
    names = stored | fetched
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("symbol", "name"))
        writer.writerows(sorted(names.items()))
    print(f"names {len(names)} symbols stored")

def refresh(symbols: tuple[str, ...] = (),
            series: tuple[str, ...] = SERIES) -> None:
    """Refresh every selected symbol and series."""
    symbols = symbols or WATCHLIST
    for name in series:
        for symbol in symbols:
            write_bars(symbol, ADJUST[name], STORE / name / f"{symbol}.csv")
            time.sleep(DELAY)
    write_names(symbols, STORE / "names.csv")


if __name__ == "__main__":

    match sys.argv[1:]:
        case ["refresh", *symbols]:
            refresh(tuple(symbols))
        case _:
            raise SystemExit("usage: python source.py refresh [symbol ...]")
