import csv
import math
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from source import Bar, Bars
from watches import WATCHLIST

type Money = float           # cash, prices, and any amount of money
type Quantity = int          # a count of shares

def history(*closes: Money) -> Bars:
    """Build flat example bars from literal closes: open=high=low=close."""
    return tuple(
        Bar(date(2026, 1, 1) + timedelta(days=offset),
            close, close, close, close, 0)
        for offset, close in enumerate(closes)
    )

@dataclass(frozen=True)
class Instrument:
    """One tradable name and its relevant information."""

    symbol: str
    name: str
    bars: Bars
    adjusted: Bars = ()

    @property
    def closes(self) -> tuple[Money, ...]:
        """Unadjusted closes, oldest first: the mark's input."""
        return tuple(bar.close for bar in self.bars)

    @property
    def adjusted_closes(self) -> tuple[Money, ...]:
        """Dividend-continuous closes: for returns, never for marks."""
        return tuple(bar.close for bar in self.adjusted)

type Market = dict[str, Instrument]     # symbol -> instrument

def mark(market: Market, symbol: str) -> Money:
    """The latest close, which is the one price a session works from."""
    return market[symbol].bars[-1].close

# use hardlink for the moment
STORE = Path.home() / "git" / "notes" / "projects" / "trade" / "bars"
SERIES = ("raw", "qfq")
ADJUST = {"raw": "", "qfq": "qfq"}

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

WINDOW = 60

def read(symbol: str, series: str) -> Bars:
    """One stored series for one symbol, oldest first."""
    with open(STORE / series / f"{symbol}.csv", newline="") as handle:
        return tuple(
            Bar(date.fromisoformat(row["date"]),
                float(row["open"]), float(row["high"]),
                float(row["low"]), float(row["close"]),
                int(row["volume"]))
            for row in csv.DictReader(handle)
        )

def load_names() -> dict[str, str]:
    """Symbol -> Chinese name in the local snapshot."""
    with open(STORE / "names.csv", newline="") as handle:
        return {row["symbol"]: row["name"] for row in csv.DictReader(handle)}

def refresh(symbols: tuple[str, ...] = (),
            series: tuple[str, ...] = SERIES) -> None:
    """Fetch and store every selected symbol and series."""
    from source import DELAY, fetch_bars, fetch_names, parse_names

    symbols = symbols or WATCHLIST
    for name in series:
        for symbol in symbols:
            bars = fetch_bars(symbol, ADJUST[name])
            write_bars(STORE / name / f"{symbol}.csv", bars)
            print(f"{name:>3} {symbol} {len(bars):>4} bars "
                  f"{bars[0].date} .. {bars[-1].date}")
            time.sleep(DELAY)

    # names.csv is shared, so a subset refresh must preserve other names.
    path = STORE / "names.csv"
    names = load_names() if path.exists() else {}
    names = merge_names(names, parse_names(fetch_names(symbols)))
    write_names(path, names)
    print(f"names {len(names)} symbols stored")

def gather(as_of: date | None = None,
           window: int | None = WINDOW) -> Market:
    """Gather all relevant market info as of a date, from the snapshot."""
    names = load_names()
    market: Market = {}
    for symbol in WATCHLIST:
        bars = tuple(bar for bar in read(symbol, "raw")
                     if as_of is None or bar.date <= as_of)
        if not bars:
            continue
        # Keep only adjusted bars whose day the raw series also has. The two
        # are not always the same length: for 2 of the 11 watchlist names the
        # qfq endpoint lagged raw by a day at the leading edge. Intersecting
        # bounds the damage to "the adjusted series is a bar shorter" instead
        # of letting a return built from adjusted closes pair with a mark from
        # another day.
        days = {bar.date for bar in bars}
        adjusted = tuple(bar for bar in read(symbol, "qfq")
                         if bar.date in days)
        market[symbol] = Instrument(
            symbol, names[symbol],
            bars[-window:] if window else bars,
            adjusted[-window:] if window else adjusted,
        )
    return market
