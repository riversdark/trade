import csv
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

type Money = float           # cash, prices, and any amount of money
type Quantity = int          # a count of shares

@dataclass(frozen=True)
class Bar:
    """One day's OHLCV observation for one instrument."""
    # TODO: constraint checks? such as low <= open/close <= high

    date: date
    open: Money
    high: Money
    low: Money
    close: Money
    volume: Quantity         # 手, lots of 100 shares

type Bars = tuple[Bar, ...]             # ordered oldest first

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

# The names this account watches: its holdings plus the candidates under
# consideration. `gather` can only be as wide as what `source.py` fetches, so
# widening it is a one-line change here plus one refresh.
WATCHLIST: tuple[str, ...] = (
    # holdings
    "000528", "601226", "002389", "002272", "000519", "002414", "601212",
    # candidates
    "600036", "601318", "000001", "600519",
)

# How many bars downstream gets. The modelling layer's momentum is "the return
# over the window", so the window *is* the lookback: 60 trading days is roughly
# a quarter, and an unbounded window would have turned that into a 2.5-year
# return the moment the store grew past a handful of fixture closes.
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
    """Symbol -> Chinese name, as source.py recorded it."""
    with open(STORE / "names.csv", newline="") as handle:
        return {row["symbol"]: row["name"] for row in csv.DictReader(handle)}

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
