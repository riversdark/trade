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

# pretend to be browser traffic
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

def test() -> None:
    """Fetch sample responses and exercise the snapshot writers."""
    from tempfile import TemporaryDirectory
    from urllib.parse import urlparse

    parsed = urlparse(KLINE)
    assert parsed.scheme == "https" and parsed.hostname == "web.ifzq.gtimg.cn"
    assert RETRIES > 1 and DELAY > 0
    print(f"politeness: {RETRIES} tries, {DELAY}s pacing, {BATCH} names/request")

    wire = get(f"{KLINE}?param=sz000528,day,1900-01-01,"
               f"{date.today().isoformat()},{DEPTH},qfq")
    rows = json.loads(wire)["data"]["sz000528"]["qfqday"]
    assert rows
    print(type(wire).__name__)
    print(rows[0])

    assert market_code("000528") == "sz000528"
    assert market_code("600519") == "sh600519"
    assert market_code("830799") == "bj830799"
    print("codes: 000528 -> sz, 600519 -> sh, 830799 -> bj")

    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "qfq" / "000528.csv"
        write_bars("000528", "qfq", path)
        lines = path.read_text().splitlines()
        assert lines[0] == "date,open,high,low,close,volume"
        assert len(lines[1].split(",")) == 6
        print(lines[:2])

    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "names.csv"
        path.write_text("symbol,name\n999999,existing\n")
        write_names(("000528", "601226"), path)
        with open(path, newline="") as handle:
            names = {row["symbol"]: row["name"]
                     for row in csv.DictReader(handle)}
        assert names["999999"] == "existing"
        assert names["000528"] and names["601226"]
        print(names)
    print("Source tests passed.")


if __name__ == "__main__":

    match sys.argv[1:]:
        case []:
            test()
        case ["refresh", *symbols]:
            refresh(tuple(symbols))
        case _:
            raise SystemExit("usage: python source.py [refresh [symbol ...]]")
