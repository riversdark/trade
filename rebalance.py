"""Rebalance: beliefs plus constraints become a batch of orders.

Step five of the plan, the decision layer. It may only see `Belief`, never the
raw market, and every order it emits is an intention: execution is manual, so
an order carries a reference price and slippage will be exactly
`fill.price - order.price`.

Two guarantees are enforced here rather than hoped for:

- no buy creates a position above `max_position_weight`, because the budget is
  clamped to one cap per new name; and
- every sell is a legal lot size -- whole lots, except that an odd-lot holding
  may be sold in full when the order closes it (the A-share 零股 rule).

`check_batch` re-asserts both afterwards and *returns* whatever T+1 makes
unfixable, so the caller can report it instead of crashing.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal

from gather import Instrument, Market, Price, history, mark
from infer import Beliefs, infer
from portfolio import Lot, Portfolio, Position, Side


@dataclass(frozen=True)
class Order:
    """An intention, not an execution.

    Slippage is exactly `fill.price - order.price`, which is why an order
    carries a reference price and nothing else about the future.
    """

    symbol: str
    name: str
    side: Side
    quantity: int                       # whole lots, or a full odd-lot exit
    price: Price                        # reference mark, for the ticket only
    reason: str

    @property
    def value(self) -> Price:
        return self.quantity * self.price


def legal_sell(position: Position, quantity: int, lot_size: int) -> int:
    """The largest legal sell at or below ``quantity``.

    Sells are whole lots, with one exception borrowed from the A-share rule
    for 零股: an odd-lot holding may be sold in full, but only when the order
    closes the position. So a partial sell rounds down to a lot, while a full
    exit is allowed to be odd.
    """
    if quantity == position.quantity:
        return quantity
    return quantity // lot_size * lot_size


def sell_order(portfolio: Portfolio, position: Position,
               beliefs: Beliefs, as_of: date) -> Order:
    """Exit a name whose momentum has turned, or trim it back to the cap."""
    belief = beliefs[position.symbol]   # a holding missing from the market is a bug
    if belief.expected_return <= 0:
        quantity = position.available(as_of)        # T+1 still applies on the way out
        reason = f"momentum {belief.expected_return:+.2%}"
    else:
        quantity = portfolio.shares_to_sell_to_cap(position.symbol, as_of)
        reason = f"overweight {portfolio.weight(position.symbol):.1%}"
    quantity = legal_sell(position, quantity, portfolio.lot_size)
    return Order(position.symbol, position.name, Side.SELL, quantity,
                 position.price, reason)


def buy_orders(portfolio: Portfolio, beliefs: Beliefs,
               market: Market, sells: list[Order]) -> list[Order]:
    """Spend the cash the sells free, one equal slot per new name."""
    held = {p.symbol for p in portfolio.positions}
    # `sum` needs an explicit Decimal start, otherwise 0 makes the result an int.
    cash = portfolio.cash + sum((o.value for o in sells), Decimal("0"))
    cap = portfolio.max_position_weight * portfolio.equity
    budget = cash - portfolio.minimum_cash_weight * portfolio.equity

    ranked = sorted((b for s, b in beliefs.items() if s not in held),
                    key=lambda b: b.expected_return, reverse=True)
    # A name whose smallest legal lot already breaks the cap can never be a
    # position. Drop those before splitting the budget, not after: otherwise
    # they silently eat a share of the cash they can never spend.
    ranked = [b for b in ranked if b.expected_return > 0
              and mark(market, b.symbol) * portfolio.lot_size <= cap]
    if not ranked:
        return []

    # Trading at the mark leaves equity unchanged, so the batch can deploy at
    # most one cap per new name. Without this clamp, a cash-rich account with
    # few candidates buys a slot worth far more than any position may hold:
    # 90000 in one name against a 25000 cap.
    budget = min(budget, cap * len(ranked))

    slot, remaining, orders = budget / len(ranked), budget, []
    for belief in ranked:
        instrument = market[belief.symbol]
        price = mark(market, belief.symbol)
        # Money rounding, not float rounding. `int(x / y)` truncates toward
        # zero, and round() uses banker's rounding; ask Decimal for the floor.
        lots = int((min(slot, remaining) / (price * portfolio.lot_size))
                   .to_integral_value(ROUND_FLOOR))
        if lots < 1:                    # leftover cash no longer buys a lot
            continue
        quantity = lots * portfolio.lot_size
        orders.append(Order(instrument.symbol, instrument.name, Side.BUY,
                            quantity, price,
                            f"momentum {belief.expected_return:+.2%}"))
        remaining -= quantity * price
    return orders


def rebalance(portfolio: Portfolio, beliefs: Beliefs,
              market: Market, as_of: date) -> list[Order]:
    """Turn beliefs into a batch of orders.

    Sells come first: in the A-share market the proceeds are immediately
    reusable for buying, they just cannot be withdrawn until T+1.
    """
    sells = [order for order in (sell_order(portfolio, p, beliefs, as_of)
                                 for p in portfolio.positions)
             if order.quantity]
    return sells + buy_orders(portfolio, beliefs, market, sells)


def check_batch(portfolio: Portfolio, orders: list[Order],
                market: Market, as_of: date) -> dict[str, Decimal]:
    """Assert the batch's own guarantees, returning what T+1 leaves over.

    The batch promises three things: every order is a legal lot size, sells
    come first so their cash is reusable, and no buy creates a position above
    the cap. What it cannot promise is that every pre-existing overweight is
    fixed *today* -- T+1 withholds shares bought the same day -- so a position
    still over the cap is returned for the caller to report, not raised.
    """

    lot_size = portfolio.lot_size
    cap = portfolio.max_position_weight * portfolio.equity

    # Buys are always whole lots; a sell is whole lots too, unless the order
    # closes an odd-lot holding outright.
    assert all(order.quantity % lot_size == 0
               for order in orders if order.side is Side.BUY)
    assert all(order.quantity % lot_size == 0
               or order.quantity == portfolio.position(order.symbol).quantity
               for order in orders if order.side is Side.SELL)
    first_buy = next(
        (i for i, o in enumerate(orders) if o.side is Side.BUY),
        len(orders)
    )
    assert all(order.side is Side.SELL for order in orders[:first_buy])

    # Trading at the mark leaves equity unchanged, so one denominator checks
    # the whole batch.
    quantity = {p.symbol: p.quantity for p in portfolio.positions}
    for order in orders:
        delta = order.quantity if order.side is Side.BUY else -order.quantity
        quantity[order.symbol] = quantity.get(order.symbol, 0) + delta

    assert all(q >= 0 for q in quantity.values())
    assert all(quantity[o.symbol] * mark(market, o.symbol) <= cap
               for o in orders if o.side is Side.BUY)

    left_over = {s: q * mark(market, s) for s, q in quantity.items()
                 if q * mark(market, s) > cap}
    for symbol in left_over:
        sold = next((o.quantity for o in orders
                     if o.symbol == symbol and o.side is Side.SELL), 0)
        assert sold == portfolio.position(symbol).available(as_of), \
            f"{symbol} under-trimmed"
    return left_over


def test_rebalance():
    """Executable examples for the decision layer's own guarantees."""

    today = date(2026, 8, 25)

    # A cash-rich account with few candidates is exactly where an uncapped
    # slot would put 90% of equity into one name.
    market = {
        "AAA": Instrument("AAA", "A", history("10.00", "11.00")),
        "BBB": Instrument("BBB", "B", history("20.00", "22.00")),
    }
    rich = Portfolio(cash=Decimal("1000000"), positions=())
    orders = buy_orders(rich, infer(market), market, [])
    cap = rich.max_position_weight * rich.equity
    assert len(orders) == 2
    assert all(order.value <= cap for order in orders)

    # Odd lots: a partial sell is whole lots, but a full exit may be odd.
    odd = Position("X", "X", (Lot(today, 750, Decimal("8.0")),), Decimal("10.0"))
    assert legal_sell(odd, 650, 100) == 600     # 150 would be left behind
    assert legal_sell(odd, 750, 100) == 750     # closes the holding outright
    assert legal_sell(odd, 700, 100) == 700     # already whole lots

    # T+1 can make the cap unreachable: nothing bought today is sellable, so
    # the batch is empty and the breach is reported, not asserted away.
    stale = {"X": Instrument("X", "X", history("9.00", "10.00"))}
    held_today = Portfolio(
        cash=Decimal("70000"),
        positions=(Position("X", "X", (Lot(today, 3000, Decimal("10.0")),),
                            Decimal("10.0")),),
    )
    nothing = rebalance(held_today, infer(stale), stale, today)
    assert nothing == []
    assert check_batch(held_today, nothing, stale, today) == {"X": Decimal("30000")}

    # Overweight and *still in favour*: trim back to the cap, not to zero. This
    # is the decision that picks `shares_to_sell_to_cap`, whose arithmetic
    # `portfolio.py` proves in isolation -- the two tests meet at the same
    # 1800-share answer rather than restating each other.
    fat = Portfolio(
        cash=Decimal("20000"),
        positions=(Position("X", "X", (Lot(date(2026, 8, 21), 3000,
                                           Decimal("8.0")),),
                            Decimal("10.0")),),
    )
    up = {"X": Instrument("X", "X", history("9.00", "10.00"))}
    trim = sell_order(fat, fat.position("X"), infer(up), today)
    assert trim.side is Side.SELL
    assert trim.quantity == 1800        # smallest whole-lot trim to the 25% cap
    assert trim.reason.startswith("overweight")

    print("rebalance tests passed.")


if __name__ == "__main__":

    test_rebalance()
