import csv
from dataclasses import dataclass
from datetime import date

from source import STORE
from watches import WATCHLIST

type Money = float           # cash, prices, and any amount of money
type Quantity = int          # a count of shares

@dataclass(frozen=True)
class Bar:
    """One day's OHLCV observation for one instrument."""

    date: date
    open: Money
    high: Money
    low: Money
    close: Money
    volume: Quantity

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

def read(symbol: str, series: str) -> Bars:
    """Read one stored series for one symbol, oldest first."""
    with open(STORE / series / f"{symbol}.csv", newline="") as handle:
        return tuple(
            Bar(date.fromisoformat(row["date"]),
                float(row["open"]), float(row["high"]),
                float(row["low"]), float(row["close"]),
                int(row["volume"]))
            for row in csv.DictReader(handle)
        )

def load_names() -> dict[str, str]:
    """Read the shared symbol -> name table from the snapshot."""
    with open(STORE / "names.csv", newline="") as handle:
        return {row["symbol"]: row["name"] for row in csv.DictReader(handle)}

def mark(market: Market, symbol: str) -> Money:
    """The latest raw close, which is the one price a session works from."""
    return market[symbol].bars[-1].close

WINDOW = 60

def gather(as_of: date | None = None,
           window: int | None = WINDOW) -> Market:
    """Gather the watchlist from the snapshot as of a date."""
    names = load_names()
    market: Market = {}
    for symbol in WATCHLIST:
        bars = tuple(bar for bar in read(symbol, "raw")
                     if as_of is None or bar.date <= as_of)
        days = {bar.date for bar in bars}
        adjusted = tuple(bar for bar in read(symbol, "qfq")
                         if bar.date in days)
        market[symbol] = Instrument(
            symbol, names[symbol],
            bars[-window:] if window else bars,
            adjusted[-window:] if window else adjusted,
        )
    return market
