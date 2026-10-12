"""The fills ledger: an account's history, folded into positions and cash.

`portfolio.py` describes an account *state*; this module describes how that
state came to be. A ledger is an ordered tuple of entries:

    CashFlow  cash entering (a deposit, later a dividend) or leaving
    Fill      one execution: a buy opens a lot, a sell consumes lots FIFO

`replay` folds the ledger into a `Portfolio`, so what the next session reasons
about is what actually happened, not what was intended. Orders are absent by
design: an order is an intention, and only its fill moves money. Slippage is
the gap between the two, and an order that never fills leaves no trace here.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from portfolio import Lot, Portfolio, Position, Side


@dataclass(frozen=True)
class CashFlow:
    """Cash entering (positive) or leaving (negative) the account.

    A deposit and a withdrawal are the same event with opposite signs, so one
    entry covers both -- and, later, dividends and fees.
    """

    date: date
    amount: Decimal


@dataclass(frozen=True)
class Fill:
    """One execution: what the broker actually did.

    A fill carries the *executed* price, so it also records the slippage
    against the order's reference price (``fill.price - order.price``). A
    partial fill is just a fill: the ledger records what happened, not what
    was asked for.
    """

    symbol: str
    date: date
    side: Side
    quantity: int
    price: Decimal


# The ledger is a plain tuple, not a class: order is the only structure it has.
type Entry = CashFlow | Fill
type Ledger = tuple[Entry, ...]


def cash_delta(entry: Entry) -> Decimal:
    """The signed cash effect of one entry, independent of the lot book.

    Note the decomposition: cash never needs to know which lot a sale
    consumed, so it is the sum of the flows rather than a side effect of
    matching.
    """

    match entry:
        case CashFlow(amount=amount):
            return amount
        case Fill(side=Side.BUY, quantity=quantity, price=price):
            return -quantity * price
        case Fill(side=Side.SELL, quantity=quantity, price=price):
            return quantity * price


def sell_lots(lots, quantity, date):
    """Consume available lots in FIFO order.

    A lot bought on ``date`` is not yet available (T+1), so it is skipped. If
    even the older lots cannot cover the sale, the ledger is wrong and we say
    so loudly rather than inventing shares.
    """

    remaining = quantity
    result = []
    for lot in lots:
        consumed = 0
        if remaining and lot.purchase_date < date:
            consumed = min(lot.quantity, remaining)
            remaining -= consumed
        if lot.quantity > consumed:
            result.append(Lot(lot.purchase_date, lot.quantity - consumed, lot.price))

    if remaining:
        raise ValueError(f"not enough shares available to sell: {remaining}")
    return result


def lot_book(fills) -> dict[str, tuple[Lot, ...]]:
    """Fold fills into open lots per symbol: buys open, sells consume FIFO.

    Symbols whose lots have all been sold are dropped, so the book is exactly
    the set of open positions.
    """

    book: dict[str, list[Lot]] = {}
    for fill in fills:
        if fill.side is Side.BUY:
            book.setdefault(fill.symbol, []).append(
                Lot(fill.date, fill.quantity, fill.price)
            )
        else:
            book[fill.symbol] = sell_lots(
                book.get(fill.symbol, []), fill.quantity, fill.date
            )
    return {symbol: tuple(lots) for symbol, lots in book.items() if lots}


def replay(ledger: Ledger, as_of: date, *,
           names: dict[str, str], prices: dict[str, Decimal]) -> Portfolio:
    """Fold the ledger into the account state at ``as_of``.

    Entries dated after ``as_of`` are ignored, so one ledger answers "what did
    the account look like then?" at any moment -- which is what a backtest
    needs. Cash is the sum of the flows; positions are the open lots marked at
    ``prices``, named by ``names``.
    """

    entries = [entry for entry in ledger if entry.date <= as_of]
    lots = lot_book(entry for entry in entries if isinstance(entry, Fill))
    positions = tuple(Position(symbol, names[symbol], open_lots, prices[symbol])
                      for symbol, open_lots in lots.items())
    cash = sum((cash_delta(entry) for entry in entries), Decimal("0"))
    return Portfolio(cash, positions)


def test_ledger():
    """Executable examples: deposit, buy, partial FIFO sale, and T+1."""

    yesterday = date(2026, 8, 20)
    today = date(2026, 8, 21)
    tomorrow = date(2026, 8, 22)
    later = date(2026, 8, 25)

    ledger = (
        CashFlow(yesterday, Decimal("20000.0")),
        Fill("TEST", today, Side.BUY, 1000, Decimal("10.0")),
        Fill("TEST", later, Side.SELL, 400, Decimal("12.0")),
    )
    names = {"TEST": "Test"}
    prices = {"TEST": Decimal("11.0")}

    portfolio = replay(ledger, later, names=names, prices=prices)

    # Cash is the sum of the flows: 20000 - 10000 + 4800.
    assert portfolio.cash == Decimal("14800.0")
    # The sale consumed the first lot FIFO, leaving the rest at its price.
    assert portfolio.position("TEST").quantity == 600
    assert portfolio.position("TEST").cost == Decimal("10.0")
    assert portfolio.value == Decimal("6600.0")
    assert portfolio.equity == Decimal("21400.0")

    # `as_of` is a filter, not decoration: before the sale, nothing sold.
    before_sale = replay(ledger, tomorrow, names=names, prices=prices)
    assert before_sale.position("TEST").quantity == 1000
    assert before_sale.cash == Decimal("10000.0")
    assert before_sale.position("TEST").available(tomorrow) == 1000
    # ...and the lot bought today is not yet available today.
    assert before_sale.position("TEST").available(today) == 0

    # T+1: shares bought today cannot be sold today.
    try:
        replay((Fill("TEST", today, Side.BUY, 100, Decimal("10.0")),
                Fill("TEST", today, Side.SELL, 100, Decimal("12.0"))),
               today, names=names, prices=prices)
    except ValueError as error:
        assert "not enough shares" in str(error)
    else:
        assert False, "same-day sale should not be available under T+1"

    # Selling more than the lot book holds is not a negative position.
    try:
        replay((Fill("TEST", today, Side.BUY, 100, Decimal("10.0")),
                Fill("TEST", tomorrow, Side.SELL, 200, Decimal("12.0"))),
               tomorrow, names=names, prices=prices)
    except ValueError as error:
        assert "not enough shares" in str(error)
    else:
        assert False, "an oversell should be rejected"

    # A symbol sold out entirely leaves no position behind, only cash.
    closed = replay((Fill("TEST", today, Side.BUY, 100, Decimal("10.0")),
                     Fill("TEST", tomorrow, Side.SELL, 100, Decimal("12.0"))),
                    tomorrow, names=names, prices=prices)
    assert closed.positions == ()
    assert closed.cash == Decimal("200.0")

    print("ledger tests passed.")


if __name__ == "__main__":

    test_ledger()
