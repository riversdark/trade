"""Gather: the market as it looks right now.

Step one of the plan. `gather` returns a `Market`: one `Instrument` per
symbol, carrying the recent bars everything downstream reasons about. The last
bar's close is the mark, which is why this module also owns the single price
source: `retrieve` values lots with `mark`, and `rebalance` trades at it, so a
session can never value and trade at different prices.

This module reads a local snapshot and never touches the network. `source.py`
fetches, deliberately and once, into `bars/`. That split is not tidiness: the
eastmoney endpoints behind akshare's `stock_zh_a_hist` refuse bulk history
requests outright (verified: every attempt dies with `RemoteDisconnected`),
and any design that wants a request per symbol per session turns a daily job
into a rate-limit incident. Fetching is a step you run; gathering is a step you
can run as often as you like, offline.

Two series are kept per symbol, and the distinction earns its keep:

  bars/raw/  unadjusted -- the prices actually traded, so a mark matches a
             broker fill and a replayed ledger reconciles to the cent.
  bars/qfq/  forward-adjusted -- continuous across dividends, so returns and
             momentum are not polluted by ex-dividend price jumps.

`Instrument.bars` is the raw series because marks are raw. `Instrument.adjusted`
exists for the modelling layer, which wants returns rather than prices.
Pinning `as_of` makes a session point-in-time: refreshing the snapshot adds
newer bars without moving what an old date sees, which is what a backtest needs
and what keeps `test_gather` stable while the store keeps growing.
"""

import csv
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path


type Price = Decimal
type History = tuple[Price, ...]        # ordered closes, oldest first
type Market = dict[str, Instrument]     # symbol -> instrument


@dataclass(frozen=True)
class Bar:
    """One day's OHLCV observation for one instrument.

    `volume` is in 手, lots of 100 shares -- the unit A-share quotes speak and
    the same one `Portfolio.lot_size` already encodes, so no conversion sits
    between the data and the decision. `date` is a trading day: the source is
    end-of-day, so there is no intraday bar to confuse it with.
    """

    date: date
    open: Price
    high: Price
    low: Price
    close: Price
    volume: int


type Bars = tuple[Bar, ...]


@dataclass(frozen=True)
class Instrument:
    """One tradable name and its relevant information.

    `bars` is unadjusted and `adjusted` is qfq, both oldest first. `adjusted`
    defaults to empty so an example that has only closes to show need not
    invent a dividend history, but `gather` always fills it from the snapshot.

    `frozen=True` makes instances immutable and hashable, which is what lets
    entire snapshots be treated as values rather than as mutable state.
    """

    symbol: str
    name: str
    bars: Bars
    adjusted: Bars = ()

    @property
    def closes(self) -> History:
        "The mark's input: unadjusted closes, oldest first."
        return tuple(bar.close for bar in self.bars)

    @property
    def adjusted_closes(self) -> History:
        "Dividend-continuous closes: for returns, never for marks."
        return tuple(bar.close for bar in self.adjusted)


# --- the snapshot on disk ---------------------------------------------------

STORE = Path(__file__).parent / "bars"
SERIES = ("raw", "qfq")

# The names this account actually watches: its holdings plus the candidates
# under consideration. No indices, sectors or fundamentals yet -- `gather` can
# only be as wide as what `source.py` fetches, and widening it is a one-line
# change to this tuple plus one `python source.py`.
WATCHLIST: tuple[str, ...] = (
    # holdings
    "000528", "601226", "002389", "002272", "000519", "002414", "601212",
    # candidates
    "600036", "601318", "000001", "600519",
)

# How many bars downstream gets. The modelling layer's momentum is "the return
# over the window", so the window *is* the lookback: 60 trading days is roughly
# a quarter, and a naively unbounded window would have made it a 2.5-year
# return the moment the store grew past a handful of fixture closes.
WINDOW = 60


def load(symbol: str, series: str) -> Bars:
    """One symbol's stored series, oldest first.

    A missing file raises here, naming the path. That is the loud failure this
    design wants: an empty market would let `rebalance` conclude "nothing to
    do" and quietly produce no orders at all.
    """
    with open(STORE / series / f"{symbol}.csv", newline="") as handle:
        return tuple(
            Bar(date.fromisoformat(row["date"]),
                Decimal(row["open"]), Decimal(row["high"]),
                Decimal(row["low"]), Decimal(row["close"]),
                int(row["volume"]))
            for row in csv.DictReader(handle)
        )


def load_names() -> dict[str, str]:
    "symbol -> Chinese name, as `source.py` recorded it."
    with open(STORE / "names.csv", newline="") as handle:
        return {row["symbol"]: row["name"] for row in csv.DictReader(handle)}


def gather(as_of: date | None = None, window: int | None = WINDOW) -> Market:
    """Gather all relevant info from the open market.

    Include macro indices, sector trends, fundamentals, price histories, etc.
    Currently the price history of the watchlist: unadjusted and adjusted
    OHLCV bars, read from the local snapshot.

    `as_of` filters bars to that date or earlier, so the same snapshot answers
    "what does the market look like now" and "what did it look like on
    2026-08-25". A symbol with no bars on or before `as_of` is left out, which
    is the honest answer for a date before its listing.

    `window` keeps the last N bars, or everything stored when it is None: the
    window *is* the lookback `infer` reads, so it is a modelling choice and it
    is passed explicitly rather than hidden in the snapshot's depth.

    Widening the market no longer means editing a fixture: add the symbol to
    `WATCHLIST` and run `source.py`.
    """
    names = load_names()
    market: Market = {}
    for symbol in WATCHLIST:
        bars = tuple(bar for bar in load(symbol, "raw")
                     if as_of is None or bar.date <= as_of)
        if not bars:
            continue
        # Keep only adjusted bars whose day the raw series also has. The two
        # are not always the same length: for 2 of the 11 watchlist names the
        # qfq endpoint lags raw by a day at the leading edge (it still had no
        # 2026-09-29 bar when raw did). Intersecting bounds the damage to "the
        # adjusted series is a bar shorter" instead of letting a return built
        # from adjusted closes silently pair with a mark from another day.
        days = {bar.date for bar in bars}
        adjusted = tuple(bar for bar in load(symbol, "qfq")
                         if bar.date in days)
        market[symbol] = Instrument(
            symbol, names[symbol],
            bars[-window:] if window else bars,
            adjusted[-window:] if window else adjusted,
        )
    return market


def mark(market: Market, symbol: str) -> Price:
    "The latest close price."
    return market[symbol].closes[-1]


# --- example data -----------------------------------------------------------

def history(*closes: str) -> Bars:
    """Build a bar history from literal strings: Decimal('7.60'), never 7.60.

    Each close becomes a flat bar -- open, high and low all equal the close,
    volume zero -- because an example about orders or signals should not have
    to invent OHLCV it never looks at. Real OHLCV comes from the snapshot, and
    the dates here are synthetic for the same reason.
    """
    return tuple(
        Bar(date(2026, 1, 1) + timedelta(days=offset),
            price, price, price, price, 0)
        for offset, price in enumerate(Decimal(close) for close in closes)
    )


def test_gather():
    """Executable example: the snapshot is filtered by date, and the mark is
    the latest close at or before it."""

    as_of = date(2026, 8, 25)
    market = gather(as_of)
    instrument = market["000528"]

    print(f"{len(market)} instruments, {instrument.symbol} {instrument.name} "
          f"{len(instrument.bars)} bars, mark {mark(market, '000528')}")

    assert set(market) == set(WATCHLIST)
    # `as_of` is a filter, not decoration: no bar is from after the date.
    assert all(bar.date <= as_of for bar in instrument.bars)
    assert len(instrument.bars) == WINDOW
    assert mark(market, "000528") == instrument.bars[-1].close
    # OHLCV is internally consistent, which is the cheapest check that the
    # source's column order -- date, open, CLOSE, HIGH, LOW, volume -- was
    # read as promised rather than transposed.
    assert all(bar.low <= bar.close <= bar.high for bar in instrument.bars)
    assert all(bar.low <= bar.open <= bar.high for bar in instrument.bars)
    # Adjusted bars never invent a day the raw series lacks, and the two still
    # cover the same period: an adjusted close and a mark can be joined on
    # date, which is what lets a signal read one and a valuation the other.
    raw_days = {bar.date for bar in instrument.bars}
    adjusted_days = {bar.date for bar in instrument.adjusted}
    assert adjusted_days <= raw_days
    assert len(raw_days & adjusted_days) >= WINDOW - 1

    # The trading calendar is not decoration, it is data: every watchlist name
    # shares it, so a day missing from one is a holiday or a data gap and not a
    # fluke of one symbol. Keeping raw and adjusted on it is what makes a
    # cross-sectional comparison on a given date mean the same thing for all.
    assert all({bar.date for bar in other.bars} == raw_days
               for other in market.values())

    # Asking for an earlier date answers with an earlier market, from the same
    # snapshot: this is the whole of what a backtest needs from `gather`.
    earlier = gather(date(2026, 4, 1))
    assert all(bar.date <= date(2026, 4, 1) for bar in earlier["000528"].bars)
    assert mark(earlier, "000528") != mark(market, "000528")

    print("gather tests passed.")


if __name__ == "__main__":

    test_gather()
