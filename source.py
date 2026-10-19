import csv
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from market import STORE, WATCHLIST, Bar, Bars, load_names

KLINE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
QUOTE = "https://qt.gtimg.cn/q="

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) notes-trade/0.1"}

DEPTH = 640     # The endpoint's own cap, about two and a half years
DELAY = 0.35    # Seconds between symbol requests
BATCH = 50      # symbols per quote request
RETRIES = 3

# The store's series names are about intent; the API's `adjust` values are
# about the wire. Keep the translation in one place.
ADJUST = {"raw": "", "qfq": "qfq"}

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
    """Decode one fqkline response into bars, oldest first."""
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
    """One symbol's full stored window: a single request."""
    code = market_code(symbol)
    span = f"1900-01-01,{date.today().isoformat()}"
    payload = get(f"{KLINE}?param={code},day,{span},{DEPTH},{adjust}")
    return parse_bars(payload, symbol, adjust)

def parse_names(text: str) -> dict[str, str]:
    """Decode a `qt` response into symbol -> name."""
    names = {}
    for line in text.split(";"):
        fields = line.split("~")
        # A code with no data answers with a short line such as
        # `v_pv_none_match="1"`, which must not become a name.
        if len(fields) > 3 and fields[2].isdigit():
            names[fields[2]] = "".join(fields[1].split())
    return names

def fetch_names(symbols: tuple[str, ...]) -> dict[str, str]:
    """Every name in one request per BATCH symbols."""
    codes = [market_code(symbol) for symbol in symbols]
    names: dict[str, str] = {}
    for start in range(0, len(codes), BATCH):
        chunk = codes[start:start + BATCH]
        # GBK, not UTF-8: the endpoint is an old one and answers in it.
        names |= parse_names(get(QUOTE + ",".join(chunk), encoding="gbk"))
    return names

def merge_names(stored: dict[str, str],
                fetched: dict[str, str]) -> dict[str, str]:
    """Fetched names win; names of symbols not asked about survive."""
    return stored | fetched

def write_bars(path: Path, bars: Bars) -> None:
    """Overwrite the file with the whole history, oldest first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("date", "open", "high", "low", "close", "volume"))
        writer.writerows(
            (bar.date.isoformat(), bar.open, bar.high, bar.low, bar.close,
             bar.volume)
            for bar in bars)

def write_names(path: Path, names: dict[str, str]) -> None:
    """Write the whole symbol -> name table, sorted."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("symbol", "name"))
        writer.writerows(sorted(names.items()))

def refresh(symbols: tuple[str, ...] = WATCHLIST,
            series: tuple[str, ...] = ("raw", "qfq")) -> None:
    """Fetch and store every symbol and series, then the names."""
    for name in series:
        for symbol in symbols:
            bars = fetch_bars(symbol, ADJUST[name])
            write_bars(STORE / name / f"{symbol}.csv", bars)
            print(f"{name:>3} {symbol} {len(bars):>4} bars "
                  f"{bars[0].date} .. {bars[-1].date}")
            time.sleep(DELAY)

    # Bars are one file per symbol, so refreshing a subset is partial by
    # construction. `names.csv` is a single shared file, so it is the one place
    # a subset refresh could quietly forget the symbols it was not asked
    # about -- and `gather` would then raise a KeyError for every one of them.
    path = STORE / "names.csv"
    names = load_names() if path.exists() else {}
    names = merge_names(names, fetch_names(symbols))
    write_names(path, names)
    print(f"names {len(names)} symbols stored")

if __name__ == "__main__":

    match sys.argv[1:]:
        case ["refresh", *symbols]:
            refresh(tuple(symbols) or WATCHLIST)
        case _:
            raise SystemExit("usage: python source.py refresh [symbol ...]")
