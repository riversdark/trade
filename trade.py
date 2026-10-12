"""One trading session, end to end.

    gather -> retrieve -> evaluate -> infer -> rebalance -> render

The program's whole product is a batch of orders to place by hand. Execution
is out of scope, so there is deliberately no `execute`: the fills you report
back are appended to the ledger, which is the input to the *next* session.

Every step of the plan is its own module, named after the step, so this file
is only the procession through them:

    gather     gather.py     bars -> Market
    retrieve   retrieve.py   Market + Ledger -> Portfolio
    evaluate   evaluate.py   Portfolio -> Metrics
    infer      infer.py      Market -> Beliefs               <- the modelling layer
    rebalance  rebalance.py  beliefs + constraints -> orders  <- the decision layer
    render     render.py     orders -> the ticket

`gather` comes before `retrieve` because a ledger stores executions, never
marks: the account cannot be valued without a price. `infer` and `rebalance`
stay separate because the decision layer may only see `Belief`, never the raw
market.

Learning notes are inline, next to the code that needs them.
"""

from datetime import date
from decimal import Decimal

from portfolio import Portfolio
from gather import gather
from retrieve import retrieve           # <- gather, ledger, portfolio
from evaluate import evaluate, Metrics  # <- gather, portfolio
from infer import infer                 # <- gather
from rebalance import rebalance, Order  # <- infer, gather, portfolio
from render import render               # <- rebalance, portfolio


def trade(as_of: date) -> tuple[Portfolio, Metrics, list[Order]]:
    """One session: state in, orders out.

    `as_of` is a parameter, so the same portfolio can be reasoned about at any
    moment -- which is what a backtest will need later. The replayed portfolio
    comes back too, so a caller can reconcile it without gathering twice.

    `as_of` reaches `gather` too, so a session sees only bars up to its own
    date. That is what keeps a backtest honest: no future close can leak into
    the momentum that decides today's orders.
    """
    market = gather(as_of)
    portfolio = retrieve(market, as_of)
    metrics = evaluate(portfolio)
    beliefs = infer(market)
    orders = rebalance(portfolio, beliefs, market, as_of)
    # execute the orders by hand

    return portfolio, metrics, orders


def test_trade():
    """Executable example: the six steps compose into one session.

    This runs on the real snapshot, not on fixtures, so the numbers below are a
    regression test rather than a demonstration. `as_of` is pinned to
    2026-08-25, and raw closes are never revised, so refreshing `bars/` with
    newer days cannot move any figure here.
    """

    from portfolio import Side
    from gather import gather
    from rebalance import check_batch

    # One price source: `retrieve` marks the lots and `rebalance` trades at the
    # same closes, so a session cannot sell and buy at different marks.
    # Question: but we should also allow speculative orders?
    # e.g. current price is 5, sell/buy if it drops to 4.8
    as_of = date(2026, 8, 25)
    market = gather(as_of)
    portfolio, metrics, orders = trade(as_of)

    print(f"session {as_of}   equity {metrics.equity:,.2f}   "
          f"cash {metrics.cash_weight:.1%}   largest {metrics.max_weight:.1%}")

    assert metrics.equity == Decimal("48270.00")
    # The account went into the session at 1% cash against a 10% floor and half
    # its equity in one name, which is the state the orders exist to fix.
    assert metrics.cash_weight < portfolio.minimum_cash_weight
    assert "cash below minimum" in metrics.issues

    print("\nIssues with current portfolio:")
    for issue in metrics.issues:
        print(f"{issue}")

    print("\nOrders planned to execute:")
    print(render(orders))

    cash = portfolio.cash \
        + sum((o.value for o in orders if o.side is Side.SELL), Decimal("0")) \
        - sum((o.value for o in orders if o.side is Side.BUY), Decimal("0"))
    assert cash >= portfolio.minimum_cash_weight * portfolio.equity
    print(f"\nInvariants hold; cash after the batch {cash:,.2f}")

    # Every order is safe by construction, and T+1 blocks nothing here.
    assert {order.symbol for order in orders} == {
        "000528", "601226", "002389", "002272", "000519",
        "000001", "600036", "601318"}
    # Sells come first, so their cash is already available to the buys.
    first_buy = next(i for i, o in enumerate(orders) if o.side is Side.BUY)
    assert all(o.side is Side.SELL for o in orders[:first_buy])

    # verify the orders logic
    by_symbol = {order.symbol: order for order in orders}

    # Momentum has turned on five of the seven holdings, and every lot was
    # bought 2026-08-21, so T+1 has long since passed and each one leaves in
    # full. 柳工 is both the worst offender on weight (50.5%) and negative, so
    # the two rules agree on the same answer: out, not trimmed.
    assert by_symbol["000528"].side is Side.SELL
    assert by_symbol["000528"].quantity == 3000
    assert by_symbol["000519"].quantity == 200         # momentum -27.5%

    # The three candidates with positive momentum take an equal slot each,
    # whole lots only: 平安银行 1000, 招商银行 300, 中国平安 200.
    assert by_symbol["000001"].quantity == 1000
    assert by_symbol["600036"].quantity == 300
    assert by_symbol["601318"].quantity == 200

    # In favour and inside the cap: do nothing. These two are the check that
    # the batch sells on the signal and not merely to raise cash.
    assert "002414" not in by_symbol
    assert "601212" not in by_symbol

    # One lot costs more than the whole position cap, so it is never tradable.
    assert "600519" not in by_symbol

    # What `rebalance` promises the batch cannot fix: T+1 withholds shares
    # bought the same day, so a leftover overweight is reported, not raised.
    left_over = check_batch(portfolio, orders, market, as_of)
    assert left_over == {}

    print("trade tests passed.")


if __name__ == "__main__":

    test_trade()
