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
        if not bars:
            continue
        days = {bar.date for bar in bars}
        adjusted = tuple(bar for bar in read(symbol, "qfq")
                         if bar.date in days)
        market[symbol] = Instrument(
            symbol, names[symbol],
            bars[-window:] if window else bars,
            adjusted[-window:] if window else adjusted,
        )
    return market

def test() -> None:
    """Demonstrate snapshot reading and point-in-time market gathering."""
    bar = Bar(date(2026, 8, 25), 11.5, 11.8, 11.3, 11.6, 12345)
    assert bar.low <= bar.open <= bar.high
    assert bar.low <= bar.close <= bar.high
    print(f"bar: {bar.date} O{bar.open} H{bar.high} L{bar.low} "
          f"C{bar.close} V{bar.volume}")

    stored = read("000528", "raw")
    assert len(stored) > 5
    assert [item.date for item in stored] == sorted(item.date for item in stored)
    assert all(item.low <= item.close <= item.high for item in stored)
    names = load_names()
    assert names["000528"] == "柳工"
    print(f"read: {len(stored)} bars, {stored[0].date} .. {stored[-1].date}")

    as_of = date(2026, 8, 25)
    snapshot = gather(as_of)
    assert all(len(inst.bars) <= WINDOW for inst in snapshot.values())
    assert all(bar.date <= as_of for inst in snapshot.values()
               for bar in inst.bars)
    assert all(tuple(bar.date for bar in inst.bars)
               == tuple(bar.date for bar in inst.adjusted)
               for inst in snapshot.values())
    print(f"gather: {len(snapshot)} instruments, {WINDOW} bar window, "
          f"mark 000528 {mark(snapshot, '000528')}")

    whole = gather(as_of, window=None)
    earlier = gather(date(2026, 6, 1))
    assert len(whole["000528"].bars) >= len(snapshot["000528"].bars)
    assert mark(earlier, "000528") != mark(snapshot, "000528")
    assert gather(date(2020, 1, 1)) == {}
    print(f"history: {len(whole['000528'].bars)} stored vs "
          f"{len(snapshot['000528'].bars)} kept; "
          f"earlier mark {mark(earlier, '000528')}")
    print("Market tests passed.")


if __name__ == "__main__":
    test()
