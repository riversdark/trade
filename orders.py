"""Turn account state and beliefs into manual order intentions."""
from dataclasses import dataclass
from datetime import date
from math import ceil, floor

from account import Account, Lot, Position, Side
from inference import Beliefs, infer
from market import Money, Quantity, gather

@dataclass(frozen=True)
class Rules:
    """Limits used when allocating orders."""

    cash_reserve: float = 0.10
    max_position: float = 0.15
    lot_size: Quantity = 100

@dataclass(frozen=True)
class Order:
    """One intended trade at a reference price, with its rationale."""

    symbol: str
    side: Side
    quantity: Quantity
    price: Money
    reason: str

type Orders = tuple[Order, ...]

def _whole_lots(quantity: Quantity, lot_size: Quantity) -> Quantity:
    return quantity // lot_size * lot_size

def _sell_quantity(position: Position, as_of: date, rules: Rules,
                   exit_position: bool, equity: Money) -> Quantity:
    """Choose a sell amount, respecting T+1 and whole-lot partial trades."""
    available = position.available(as_of)
    if not available:
        return 0
    if exit_position and available == position.quantity:
        return available
    if exit_position:
        return _whole_lots(available, rules.lot_size)
    excess_value = max(0.0, position.value - rules.max_position * equity)
    needed_lots = ceil(excess_value / (position.price * rules.lot_size))
    return min(available, needed_lots * rules.lot_size)

def rebalance(acct: Account, blfs: Beliefs, rules: Rules,
              as_of: date) -> Orders:
    """Sell nonpositive beliefs or excess weight, then buy from current cash."""
    equity = acct.equity
    positions = {position.symbol: position for position in acct.positions}
    sells = []
    for position in acct.positions:
        belief = blfs.get(position.symbol)
        exit_position = belief is None or belief.expected_return <= 0
        quantity = _sell_quantity(
            position, as_of, rules, exit_position, equity,
        )
        if quantity:
            reason = ("belief is nonpositive or unavailable" if exit_position
                      else "reduce position to its cap")
            sells.append(Order(position.symbol, Side.SELL, quantity,
                               position.price, reason))

    # Sell proceeds are deliberately excluded: only cash already in the account
    # can fund these buy intentions.
    cash_to_spend = max(0.0, acct.cash - rules.cash_reserve * equity)
    buys = []
    candidates = sorted(
        ((symbol, belief) for symbol, belief in blfs.items()
         if belief.expected_return > 0),
        key=lambda item: item[1].expected_return,
        reverse=True,
    )
    for symbol, belief in candidates:
        current_value = positions[symbol].value if symbol in positions else 0.0
        room = max(0.0, rules.max_position * equity - current_value)
        budget = min(cash_to_spend, room)
        quantity = _whole_lots(floor(budget / belief.mark), rules.lot_size)
        if quantity:
            cost = quantity * belief.mark
            buys.append(Order(symbol, Side.BUY, quantity, belief.mark,
                              "positive expected return; highest-ranked affordable allocation"))
            cash_to_spend -= cost

    return tuple(sells + buys)

def test():
    """Demonstrate buying and T+1 selling with the local market snapshot."""
    as_of = date(2026, 8, 25)
    market = gather(as_of, 60)
    beliefs = infer(market)
    rules = Rules()

    cash_account = Account(50000.0, ())
    buy_orders = rebalance(cash_account, beliefs, rules, as_of)
    assert all(order.side is Side.BUY for order in buy_orders)
    assert all(order.quantity % rules.lot_size == 0 for order in buy_orders)
    assert all(order.quantity * order.price <= rules.max_position * cash_account.equity
               for order in buy_orders)
    assert sum(order.quantity * order.price for order in buy_orders) \
        <= cash_account.cash - rules.cash_reserve * cash_account.equity
    print("Buys:", buy_orders)

    symbol = next(symbol for symbol, belief in beliefs.items()
                  if belief.expected_return <= 0)
    mark = beliefs[symbol].mark
    position = Position(
        symbol, market[symbol].name,
        (Lot(date(2026, 8, 24), 100, mark),
         Lot(as_of, 50, mark)),
        mark,
    )
    sell_orders = rebalance(
        Account(10000.0, (position,)), {symbol: beliefs[symbol]}, rules, as_of,
    )
    assert len(sell_orders) == 1
    assert sell_orders[0].side is Side.SELL
    assert sell_orders[0].quantity == 100
    print("T+1 sell:", sell_orders)
    print("Rebalance examples passed.")

if __name__ == "__main__":
    test()

