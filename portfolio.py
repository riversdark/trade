"""The smallest useful portfolio vocabulary for the trading project.

This is the *state* half of the vocabulary: lots, positions, and the risk
constraints on a portfolio. The *history* that produces that state -- cash
flows and fills -- lives in `ledger.py`.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal # replacing float for exact arithmetic
from enum import Enum
from math import ceil


class Side(Enum):
    """Which way an order or fill moves a position."""

    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class Lot:
    """One purchase: shares acquired at a price on a date.

    A position is a bag of lots, which is what makes FIFO cost basis and
    per-lot T+1 availability fall out of the data instead of being tracked
    separately.
    """

    purchase_date: date
    quantity: int
    price: Decimal


@dataclass(frozen=True)
class Position:
    symbol: str
    name: str
    lots: tuple[Lot, ...]
    price: Decimal
    thesis: str = ""

    @property
    def quantity(self) -> int:
        return sum(lot.quantity for lot in self.lots)

    @property
    def value(self) -> Decimal:
        return self.quantity * self.price

    @property
    def cost_value(self) -> Decimal:
        return sum((lot.quantity * lot.price for lot in self.lots), Decimal("0"))

    @property
    def cost(self) -> Decimal:
        return self.cost_value / self.quantity if self.quantity else Decimal("0")

    @property
    def pnl(self) -> Decimal:
        "unrealised profit & loss."
        return self.value - self.cost_value

    @property
    def return_pct(self) -> Decimal:
        return self.pnl / self.cost_value if self.cost_value else Decimal("0")

    def available(self, as_of: date) -> int:
        """Shares bought before ``as_of`` are available under T+1.

        No wall-clock default: the caller supplies the as-of date, so the
        same position can be valued at any past or future moment.
        """

        return sum(
            lot.quantity for lot in self.lots if lot.purchase_date < as_of
        )


@dataclass(frozen=True)
class Portfolio:
    """Positions plus cash: the account snapshot as of a given moment.

    The risk constraints (lot size, position and cash weights) live here
    too, so every operation on a portfolio can enforce them.
    """
    cash: Decimal
    positions: tuple[Position, ...]
    lot_size: int = 100
    max_position_weight: Decimal = Decimal("0.25")
    minimum_cash_weight: Decimal = Decimal("0.10")

    def __post_init__(self) -> None:
        symbols = [position.symbol for position in self.positions]
        duplicates = sorted(
            {symbol for symbol in symbols if symbols.count(symbol) > 1}
        )
        if duplicates:
            raise ValueError(f"duplicate position symbols: {duplicates}")

    @property
    def value(self) -> Decimal:
        return sum((position.value for position in self.positions), Decimal("0"))

    @property
    def equity(self) -> Decimal:
        return self.cash + self.value

    @property
    def cash_weight(self) -> Decimal:
        """Cash as a share of equity, zero for an emptied account.

        Equity *is* cash plus marked value, so zero equity means every weight
        is zero. Dividing anyway would raise a bare Decimal error where the
        state itself is perfectly describable.
        """
        return self.cash / self.equity if self.equity else Decimal("0")

    def position(self, symbol: str) -> Position:
        for position in self.positions:
            if position.symbol == symbol:
                return position
        raise KeyError(f"no position for symbol: {symbol}")

    def weight(self, symbol: str) -> Decimal:
        """The position's share of equity, zero for an emptied account."""
        if not self.equity:
            return Decimal("0")
        return self.position(symbol).value / self.equity

    def issues(self) -> list[str]:
        """Return simple warnings for the current portfolio."""

        issues = []
        if self.cash_weight < self.minimum_cash_weight:
            issues.append("cash below minimum")
        for position in self.positions:
            if self.weight(position.symbol) > self.max_position_weight:
                issues.append(f"{position.name}({position.symbol}) is overweight")
        return issues

    def shares_to_sell_to_cap(
        self, symbol: str, as_of: date, maximum_weight: Decimal | None = None
    ) -> int:
        """Lot-rounded sell quantity that brings the weight to the cap.

        A sale at the mark is internal: the proceeds simply become cash, so
        equity is unchanged and only the position's value drops.

            (V - s*p) / E <= w   =>   s >= (V - w*E) / p

        Returns 0 when the position is already within the cap, and at most
        the shares available under T+1 as of ``as_of``.
        """

        maximum_weight = (
            self.max_position_weight if maximum_weight is None else maximum_weight
        )
        if not 0 <= maximum_weight < 1:
            raise ValueError(f"maximum_weight must be in [0, 1): {maximum_weight}")

        position = self.position(symbol)
        excess = position.value - maximum_weight * self.equity
        if excess <= 0:
            return 0
        lots = ceil(excess / (position.price * self.lot_size))
        return min(position.available(as_of), lots * self.lot_size)


def test_portfolio():

    yesterday = date(2026, 8, 20)
    today = date(2026, 8, 21)
    tomorrow = date(2026, 8, 22)

    # A position is a bag of lots: quantity, weighted cost, and a mark.
    position = Position(
        "TEST", "Test",
        (Lot(yesterday, 100, Decimal("10.0")),
         Lot(today, 100, Decimal("8.0"))),
        Decimal("12.0"),
    )

    assert position.quantity == 200
    assert position.cost == Decimal("9.0")          # (100*10 + 100*8) / 200
    assert position.cost_value == Decimal("1800.0")
    assert position.value == Decimal("2400.0")
    assert position.pnl == Decimal("600.0")
    assert round(position.return_pct, 2) == Decimal("0.33")
    # T+1: a lot bought today is not yet sellable.
    assert position.available(today) == 100
    assert position.available(tomorrow) == 200

    # Selling to a cap: 3000 sh of X at 10 against 20000 cash is 60% of
    # equity. The sale is internal, so equity stays 50000 and the trim only
    # has to cover the excess: 17500 / 10 = 1750 sh, lot-rounded up to 1800
    # (24.0%). The old "equity shrinks as you sell" formula sold 2400 (12.0%),
    # liquidating 600 shares more than the cap required.
    ranked = Portfolio(
        cash=Decimal("20000"),
        positions=(Position("X", "Ex", (Lot(today, 3000, Decimal("8.0")),),
                            Decimal("10.0")),),
    )
    assert ranked.equity == Decimal("50000")
    assert ranked.weight("X") == Decimal("0.6")
    assert ranked.issues() == ["Ex(X) is overweight"]
    sold = ranked.shares_to_sell_to_cap("X", tomorrow)
    assert sold == 1800
    value_after = ranked.position("X").value - sold * ranked.position("X").price
    assert value_after / ranked.equity <= ranked.max_position_weight
    # ...and it is the *smallest* such trim: one lot less would not suffice.
    assert (value_after + ranked.lot_size * ranked.position("X").price) \
        / ranked.equity > ranked.max_position_weight
    # T+1: today's lot cannot be sold today, so nothing is available.
    assert ranked.shares_to_sell_to_cap("X", today) == 0

    # A position inside the cap needs no trim; thin cash is its own warning.
    light = Portfolio(
        cash=Decimal("90000"),
        positions=(Position("X", "Ex", (Lot(today, 100, Decimal("8.0")),),
                            Decimal("10.0")),),
    )
    assert light.weight("X") < light.max_position_weight
    assert light.shares_to_sell_to_cap("X", tomorrow) == 0

    # An emptied account is describable, not a bare Decimal division error.
    empty = Portfolio(Decimal("0"), ())
    assert empty.cash_weight == Decimal("0")
    assert empty.issues() == ["cash below minimum"]

    thin = Portfolio(
        cash=Decimal("1"),
        positions=(Position("X", "Ex", (Lot(today, 100, Decimal("8.0")),),
                            Decimal("10.0")),),
    )
    assert "cash below minimum" in thin.issues()

    # Unknown symbols raise a clear KeyError, not a bare StopIteration.
    try:
        ranked.position("999999")
    except KeyError as error:
        assert "999999" in str(error)
    else:
        assert False, "expected KeyError for an unknown symbol"

    # A portfolio must not contain duplicate symbols.
    try:
        Portfolio(Decimal("0"), (Position("X", "A", (), Decimal("1.0")),
                                 Position("X", "B", (), Decimal("1.0"))))
    except ValueError as error:
        assert "duplicate" in str(error)
    else:
        assert False, "duplicate symbols should be rejected"

    print("portfolio tests passed.")


if __name__ == "__main__":

    test_portfolio()
