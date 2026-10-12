"""Source: fetch the market snapshot, politely and once.

`gather` never touches the network, so this is the only module that does. Run
it deliberately:

    python source.py                      # the test, offline as usual
    python source.py refresh              # refresh the whole watchlist
    python source.py refresh 000528 600519   # refresh just these

Refreshing is not the default, so that `python source.py` behaves like every
other module in the project and stays off the network.

So this module is a thin, dependency-free client for two endpoints:

  fqkline  one request per symbol -> up to 640 daily OHLCV bars, unadjusted or
           qfq. The whole snapshot is ~22 requests.
  qt       one request -> many symbols' Chinese names. Batching here is what
           keeps the names from costing 11 separate round trips.

The politeness lives in `get` and `DELAY`: retries with exponential backoff, so
a dropped connection costs a retry rather than a hole in the snapshot, and a
pace between symbols that keeps a full refresh a background chore instead of
something that looks like an attack.

Full-history overwrite, never append, because a dividend rewrites the entire
qfq series -- appending would silently mix adjustment vintages in one file.
"""

import csv
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from decimal import Decimal
from pathlib import Path

from gather import STORE, WATCHLIST, Bar, Bars, load_names

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
    """One GET, retried, so a dropped connection is not a data gap.

    `RemoteDisconnected` is an `OSError`, so the retry catches the same
    failures that make the eastmoney route hopeless -- the difference is that
    this endpoint answers on the second try.
    """
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=HEADERS), timeout=20) as response:
                return response.read().decode(encoding, errors="replace")
        except (urllib.error.URLError, OSError):
            if attempt == RETRIES - 1:
                raise
            time.sleep(DELAY * 2 ** attempt)
    raise AssertionError("unreachable")


def market_code(symbol: str) -> str:
    """A-share symbol -> Tencent's market-prefixed code.

    The prefix is a property of the code, so it is computed, not looked up:
    6xxxxx and 9xxxxx are Shanghai, 4xxxxx and 8xxxxx Beijing, everything else
    Shenzhen.
    """
    if symbol.startswith(("6", "9")):
        return f"sh{symbol}"
    if symbol.startswith(("4", "8")):
        return f"bj{symbol}"
    return f"sz{symbol}"


def parse_bars(payload: str, symbol: str, adjust: str) -> Bars:
    """Decode one fqkline response into bars, oldest first.

    The row is `[date, open, close, high, low, volume]`, with close *before*
    high and low. That is the one thing here worth getting wrong quietly, so
    the mapping is spelled out positionally rather than left to a column list
    that a reader would have to hold in their head. Prices stay strings until
    `Decimal` sees them; nothing touches a float.
    """
    code = market_code(symbol)
    rows = json.loads(payload)["data"][code][f"{adjust}day"]
    return tuple(
        Bar(date=date.fromisoformat(row[0]),
            open=Decimal(row[1]),
            high=Decimal(row[3]),
            low=Decimal(row[4]),
            close=Decimal(row[2]),
            volume=int(Decimal(row[5])))
        for row in rows
    )


def fetch_bars(symbol: str, adjust: str) -> Bars:
    "One symbol's full stored window: a single request."
    code = market_code(symbol)
    span = f"1900-01-01,{date.today().isoformat()}"
    payload = get(f"{KLINE}?param={code},day,{span},{DEPTH},{adjust}")
    return parse_bars(payload, symbol, adjust)


def parse_names(text: str) -> dict[str, str]:
    """Decode a `qt` response into symbol -> name.

    Each line looks like `v_sz000528="51~柳    工~000528~7.36~...`, where the
    name is padded with spaces that belong to the protocol's fixed-width
    layout, not to the name. Splitting on whitespace and rejoining is what
    turns `柳    工` back into `柳工`.
    """
    names = {}
    for line in text.split(";"):
        fields = line.split("~")
        # A code with no data answers with a short line such as
        # `v_pv_none_match="1"`, which must not become a name.
        if len(fields) > 3 and fields[2].isdigit():
            names[fields[2]] = "".join(fields[1].split())
    return names


def fetch_names(symbols) -> dict[str, str]:
    "Every name in one request per BATCH symbols, which is the point of `qt`."
    codes = [market_code(symbol) for symbol in symbols]
    names: dict[str, str] = {}
    for start in range(0, len(codes), BATCH):
        chunk = codes[start:start + BATCH]
        # GBK, not UTF-8: the endpoint is an old one and answers in it.
        names |= parse_names(get(QUOTE + ",".join(chunk), encoding="gbk"))
    return names


def merge_names(stored: dict[str, str], fetched: dict[str, str]) -> dict[str, str]:
    """Fetched names win; names of symbols not asked about survive.

    `names.csv` is the one shared file in the store, so a subset refresh is
    exactly where it could quietly forget the rest of the watchlist.
    """
    return stored | fetched


def write_bars(path: Path, bars: Bars) -> None:
    "Overwrite the file with the whole history, oldest first."
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("date", "open", "high", "low", "close", "volume"))
        writer.writerows(
            (bar.date.isoformat(), bar.open, bar.high, bar.low, bar.close,
             bar.volume)
            for bar in bars
        )


def write_names(path: Path, names: dict[str, str]) -> None:
    "Write the whole symbol -> name table, sorted."
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("symbol", "name"))
        writer.writerows(sorted(names.items()))


def refresh(symbols=WATCHLIST, series=("raw", "qfq")) -> None:
    """Fetch and store every symbol and series, then the names.

    Two series with deliberately different failure modes: `raw` is immutable
    history that marks and replayed ledgers depend on, while `qfq` is rewritten
    whenever a dividend lands. Overwriting both is therefore not laziness --
    it is the only correct thing to do for `qfq`.
    """
    for name in series:
        for symbol in symbols:
            bars = fetch_bars(symbol, ADJUST[name])
            write_bars(STORE / name / f"{symbol}.csv", bars)
            print(f"{name:>3} {symbol} {len(bars):>4} bars "
                  f"{bars[0].date} .. {bars[-1].date}")
            time.sleep(DELAY)

    # Bars are one file per symbol, so refreshing a subset is partial by
    # construction. `names.csv` is a single shared file, so it is the one place
    # a subset refresh could quietly forget the symbols it was not asked about
    # -- and `gather` would then raise a KeyError for every one of them.
    path = STORE / "names.csv"
    names = load_names() if path.exists() else {}
    names = merge_names(names, fetch_names(symbols))
    write_names(path, names)
    print(f"names {len(names)} symbols stored")


def test_source():
    """Executable example: the wire format is decoded, not trusted.

    The network is deliberately not part of the test. What is worth pinning is
    the decoding -- Tencent's close-before-high-low column order and its
    space-padded names -- because those are the two silent-corruption risks,
    and both run against a captured response instead of a live one.
    """

    assert market_code("000528") == "sz000528"
    assert market_code("600519") == "sh600519"
    assert market_code("830799") == "bj830799"

    captured = json.dumps({"data": {"sz000528": {"qfqday": [
        ["2026-09-29", "7.420", "7.360", "7.460", "7.350", "222233.000"],
    ]}}})   # OCHLV order
    bar, = parse_bars(captured, "000528", "qfq")
    assert bar.date == date(2026, 9, 29)
    assert bar.open == Decimal("7.420")
    assert bar.close == Decimal("7.360")
    assert bar.high == Decimal("7.460")
    assert bar.low == Decimal("7.350")
    assert bar.volume == 222233
    assert bar.low <= bar.close <= bar.high

    assert parse_names('v_sz000528="51~\u67f3    \u5de5~000528~7.36~7.43";') == \
        {"000528": "\u67f3\u5de5"}
    assert parse_names('v_pv_none_match="1";') == {}

    # A subset refresh merges names: refreshing 600519 alone must not erase
    # 000528, which is the bug this function exists to make impossible.
    assert merge_names({"000528": "\u67f3\u5de5"}, {"600519": "\u8d35\u5dde\u8305\u53f0"}) == \
        {"000528": "\u67f3\u5de5", "600519": "\u8d35\u5dde\u8305\u53f0"}
    assert merge_names({"600519": "stale"}, {"600519": "fresh"}) == \
        {"600519": "fresh"}

    print("source tests passed.")


if __name__ == "__main__":

    command, *symbols = sys.argv[1:] or ["test"]
    if command == "refresh":
        refresh(symbols or WATCHLIST)
    elif command == "test":
        test_source()
    else:
        raise SystemExit(f"unknown command {command!r}; "
                         f"expected 'test' or 'refresh'")
