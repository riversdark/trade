import math
from dataclasses import dataclass
from datetime import date
from enum import Enum

from market import Money, Quantity




@dataclass(frozen=True)
class Lot:
    """One purchase: shares acquired at a price on a date."""

    purchase_date: date
    quantity: Quantity
    price: Money


@dataclass(frozen=True)
class Position:
    """A holding in one instrument: its lots, its name, and its mark."""

    symbol: str
    name: str
    lots: tuple[Lot, ...]
    price: Money

    @property
    def quantity(self) -> Quantity:
        return sum(lot.quantity for lot in self.lots)

    @property
    def value(self) -> Money:
        """Marked value: what the position is worth right now."""
        return self.quantity * self.price

    @property
    def cost(self) -> Money:
        """Average cost per share, weighted over the lots."""
        total = sum(lot.quantity * lot.price for lot in self.lots)
        return total / self.quantity if self.quantity else 0.0

    @property
    def pnl(self) -> Money:
        """Unrealised profit and loss against the cost basis."""
        return self.value - self.cost * self.quantity

    def available(self, as_of: date) -> Quantity:
        """Shares sellable under T+1: whose lot predates ``as_of``."""
        return sum(lot.quantity for lot in self.lots
                   if lot.purchase_date < as_of)


@dataclass(frozen=True)
class Account:
    """Cash plus open positions: the account at one moment."""

    cash: Money
    positions: tuple[Position, ...]

    @property
    def value(self) -> Money:
        """Marked value of the positions alone, excluding cash."""
        return sum(position.value for position in self.positions)

    @property
    def equity(self) -> Money:
        return self.cash + self.value

    @property
    def cash_weight(self) -> Money:
        """Cash as a share of equity, zero for an emptied account."""
        return self.cash / self.equity if self.equity else 0.0

    def position(self, symbol: str) -> Position:
        """The position in ``symbol``; a missing one is a lookup error."""
        for position in self.positions:
            if position.symbol == symbol:
                return position
        raise KeyError(f"no position for symbol: {symbol}")

    def weight(self, symbol: str) -> Money:
        """The position's share of equity, zero for an emptied account."""
        return self.position(symbol).value / self.equity if self.equity else 0.0


@dataclass(frozen=True)
class CashFlow:
    """Cash entering (positive) or leaving (negative) the account."""

    date: date
    amount: Money


class Side(Enum):
    """Which way an order or fill moves a position."""

    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        """The direction as a number: buys add shares, sells remove them."""
        return 1 if self is Side.BUY else -1


@dataclass(frozen=True)
class Fill:
    """One execution: what the broker actually did."""

    symbol: str
    date: date
    side: Side
    quantity: Quantity
    price: Money


type Entry = CashFlow | Fill
type Ledger = tuple[Entry, ...]     # ordered oldest first


LEDGER: Ledger = (
    CashFlow(date(2026, 8, 20), 50000.0),
)


def cash_delta(entry: Entry) -> Money:
    """The signed cash effect of one entry, independent of the lot book."""
    match entry:
        case CashFlow(amount=amount):
            return amount
        case Fill(side=side, quantity=quantity, price=price):
            return side.sign * -quantity * price


def sell_lots(lots: tuple[Lot, ...], quantity: Quantity, as_of: date) -> tuple[Lot, ...]:
    """Consume available lots in FIFO order, oldest first."""
    remaining = quantity
    result = []
    for lot in lots:
        consumed = min(lot.quantity, remaining) \
            if remaining and lot.purchase_date < as_of else 0
        remaining -= consumed
        if lot.quantity > consumed:
            result.append(Lot(lot.purchase_date, lot.quantity - consumed, lot.price))
    if remaining:
        raise ValueError(f"not enough shares available to sell: {remaining}")
    return tuple(result)


def lot_book(fills: tuple[Fill, ...]) -> dict[str, tuple[Lot, ...]]:
    """Fold fills into open lots per symbol: buys open, sells consume FIFO."""
    book: dict[str, list[Lot]] = {}
    for fill in fills:
        if fill.side is Side.BUY:
            book.setdefault(fill.symbol, []).append(
                Lot(fill.date, fill.quantity, fill.price))
        else:
            book[fill.symbol] = list(
                sell_lots(tuple(book.get(fill.symbol, ())), fill.quantity, fill.date)
            )
    return {symbol: tuple(lots) for symbol, lots in book.items() if lots}


def replay(ledger: Ledger, as_of: date, *,
           names: dict[str, str],
           prices: dict[str, Money]) -> Account:
    """Fold the ledger into the account state at ``as_of``."""
    entries = [entry for entry in ledger if entry.date <= as_of]
    cash = sum(cash_delta(entry) for entry in entries)
    lots = lot_book(tuple(entry for entry in entries if isinstance(entry, Fill)))
    positions = tuple(
        Position(symbol, names[symbol], open_lots, prices[symbol])
        for symbol, open_lots in lots.items()
    )
    return Account(cash, positions)
