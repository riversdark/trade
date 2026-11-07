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
        """Shares sellable under T+1: whose lot predates `as_of`."""
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
    """Fold the ledger into the account state at `as_of`."""
    entries = [entry for entry in ledger if entry.date <= as_of]
    cash = sum(cash_delta(entry) for entry in entries)
    lots = lot_book(tuple(entry for entry in entries if isinstance(entry, Fill)))
    positions = tuple(
        Position(symbol, names[symbol], open_lots, prices[symbol])
        for symbol, open_lots in lots.items()
    )
    return Account(cash, positions)

def test() -> None:
    """Demonstrate account values, FIFO lots, and ledger replay."""
    lots = (Lot(date(2026, 8, 20), 200, 11.1),
            Lot(date(2026, 8, 21), 100, 8.7))
    position = Position("TEST", "Test", lots, price=12.0)
    assert position.quantity == 300
    assert position.value == 3600.0
    assert math.isclose(position.cost, 10.3)
    assert math.isclose(position.pnl, 510.0)
    assert position.available(date(2026, 8, 21)) == 200
    assert position.available(date(2026, 8, 22)) == 300
    print(f"position: {position.quantity} sh, value {position.value:.2f}, "
          f"cost {position.cost:.2f}, pnl {position.pnl:.2f}")

    position_a = Position(
        "AAA", "A",
        (Lot(date(2026, 8, 20), 1000, 10.0),
         Lot(date(2026, 8, 25), 1000, 12.0)),
        price=11.0,
    )
    position_b = Position(
        "BBB", "B", (Lot(date(2026, 8, 20), 500, 20.0),), price=18.0,
    )
    account = Account(10000.0, (position_a, position_b))
    assert position_a.quantity == 2000
    assert position_a.value == 22000.0
    assert position_b.value == 9000.0
    assert account.value == 31000.0
    assert account.equity == 41000.0
    assert math.isclose(account.weight("AAA"), 22000.0 / 41000.0)
    assert math.isclose(account.weight("BBB"), 9000.0 / 41000.0)
    assert math.isclose(account.cash_weight, 10000.0 / 41000.0)
    empty = Account(0.0, ())
    assert empty.equity == empty.cash_weight == 0.0
    try:
        account.position("999999")
    except KeyError as error:
        assert "999999" in str(error)
    else:
        assert False, "expected KeyError for an unknown symbol"
    print(f"account: cash {account.cash:.2f}, value {account.value:.2f}, "
          f"equity {account.equity:.2f}; "
          f"AAA {account.weight('AAA'):.1%}, BBB {account.weight('BBB'):.1%}, "
          f"cash {account.cash_weight:.1%}")

    deposit = CashFlow(date(2026, 8, 20), 50000.0)
    withdrawal = CashFlow(date(2026, 8, 21), -50000.0)
    assert deposit.amount == 50000.0
    assert deposit.amount == -withdrawal.amount
    assert Side.BUY.sign == 1 and Side.SELL.sign == -1
    buy = Fill("TEST", date(2026, 8, 21), Side.BUY, 1000, 10.0)
    sell = Fill("TEST", date(2026, 8, 25), Side.SELL, 400, 12.0)
    sample_ledger: Ledger = (CashFlow(date(2026, 8, 20), 20000.0), buy, sell)
    assert [entry.date for entry in sample_ledger] == sorted(
        entry.date for entry in sample_ledger)
    assert cash_delta(deposit) == 50000.0
    assert cash_delta(buy) == -10000.0
    assert cash_delta(sell) == 4800.0
    print("cash flow and fills: deposit +50000, buy -10000, sell +4800")

    entry, = LEDGER
    assert isinstance(entry, CashFlow) and entry.amount == 50000.0
    buy_a, buy_b, sell_a = (
        date(2026, 9, 1), date(2026, 9, 8), date(2026, 9, 15),
    )
    ledger_grown = LEDGER + (
        Fill("000528", buy_a, Side.BUY, 1000, 10.0),
        Fill("600036", buy_b, Side.BUY, 1000, 40.0),
        Fill("000528", sell_a, Side.SELL, 400, 12.0),
    )
    names = {"000528": "A", "600036": "B"}
    prices = {"000528": 11.0, "600036": 39.0}
    later = date(2026, 9, 20)
    print(f"ledger: {len(LEDGER)} entry then {len(ledger_grown)}")

    assert cash_delta(entry) == 50000.0
    left = sell_lots(lots, 250, date(2026, 8, 22))
    assert [lot.quantity for lot in left] == [50]
    assert left[0].price == 8.7
    assert sell_lots(lots, 300, date(2026, 8, 22)) == ()
    try:
        sell_lots(lots, 250, date(2026, 8, 21))
    except ValueError as error:
        assert "not enough shares" in str(error)
    else:
        assert False, "today's lot should not be available under T+1"
    more_lots = (Lot(date(2026, 8, 20), 200, 11.1),
                 Lot(date(2026, 8, 20), 300, 11.1),
                 Lot(date(2026, 8, 21), 100, 8.7))
    more_left = sell_lots(more_lots, 250, date(2026, 8, 22))
    assert [lot.quantity for lot in more_left] == [250, 100]
    print(f"sell lots: 250 of [200, 100] leaves {[lot.quantity for lot in left]}")

    fills = tuple(item for item in ledger_grown if isinstance(item, Fill))
    book = lot_book(fills)
    assert set(book) == {"000528", "600036"}
    assert [lot.quantity for lot in book["000528"]] == [600]
    assert [lot.quantity for lot in book["600036"]] == [1000]
    assert book["000528"][0].price == 10.0
    assert book["600036"][0].price == 40.0
    closed = lot_book((Fill("000528", buy_a, Side.BUY, 1000, 10.0),
                       Fill("000528", sell_a, Side.SELL, 1000, 12.0)))
    assert closed == {}
    print(f"lot book: {sorted(book)}, 000528 {[lot.quantity for lot in book['000528']]}")

    opening = replay(LEDGER, date(2026, 8, 25), names=names, prices=prices)
    assert opening.cash == 50000.0 and opening.positions == ()
    account = replay(ledger_grown, later, names=names, prices=prices)
    assert account.cash == 4800.0
    assert {position.symbol for position in account.positions} == {"000528", "600036"}
    assert account.position("000528").quantity == 600
    assert account.value == 45600.0
    assert account.equity == 50400.0
    assert math.isclose(account.weight("000528"), 6600.0 / account.equity)
    assert account.position("000528").available(later) == 600
    before_sale = replay(ledger_grown, date(2026, 9, 10),
                         names=names, prices=prices)
    assert before_sale.position("000528").quantity == 1000
    assert before_sale.cash == 0.0
    assert replay(LEDGER, date(2026, 8, 19),
                  names=names, prices=prices).cash == 0.0
    on_buy_day = replay(ledger_grown, buy_a, names=names, prices=prices)
    assert on_buy_day.position("000528").quantity == 1000
    assert on_buy_day.position("000528").available(buy_a) == 0
    same_day = (Fill("000528", buy_a, Side.BUY, 100, 10.0),
                Fill("000528", buy_a, Side.SELL, 100, 12.0))
    try:
        replay(same_day, buy_a, names=names, prices=prices)
    except ValueError as error:
        assert "not enough shares" in str(error)
    else:
        assert False, "same-day sale should not be available under T+1"
    print(f"replay: cash {account.cash:.2f}, equity {account.equity:.2f}, "
          f"000528 {account.position('000528').quantity} sh")
    print("Account tests passed.")


if __name__ == "__main__":
    test()
