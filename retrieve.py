"""Retrieve: the account you have now, replayed from its ledger.

Step two of the plan. A ledger stores executions, never marks, so `retrieve`
needs the market to value the open lots -- which is why `gather` runs first.

`LEDGER` is the account's history, not a snapshot: the opening deposit and the
seven averaged buys transcribed from the broker screenshot of 2026-08-21.
From here on, every real execution is one more `Fill` appended below.
"""

from datetime import date
from decimal import Decimal

from gather import Market, gather, mark
from ledger import CashFlow, Fill, Ledger, replay
from portfolio import Portfolio, Side


def retrieve(market: Market, as_of: date) -> Portfolio:
    """The account as of `as_of`, replayed from the fills ledger.

    The ledger holds executions, never marks, so open lots are valued at the
    market's latest close. That is the whole reason `gather` runs first.
    """
    return replay(
        LEDGER, as_of,
        names={symbol: instrument.name
               for symbol, instrument in market.items()},
        prices={symbol: mark(market, symbol) for symbol in market},
    )


# The account history, not a snapshot: `replay` folds it into cash + positions,
# so `retrieve` cannot drift from what was actually executed. The opening
# deposit and the seven averaged buys are transcribed from the broker
# screenshot of 2026-08-21, and `test_retrieve` reconciles them to the cent.
LEDGER: Ledger = (
    CashFlow(date(2026, 8, 20), Decimal("56832.56")),
    Fill("000528", date(2026, 8, 21), Side.BUY, 3000, Decimal("11.0715")),
    Fill("601226", date(2026, 8, 21), Side.BUY, 1000, Decimal("6.2200")),
    Fill("002389", date(2026, 8, 21), Side.BUY, 300, Decimal("18.5000")),
    Fill("002272", date(2026, 8, 21), Side.BUY, 300, Decimal("15.0000")),
    Fill("000519", date(2026, 8, 21), Side.BUY, 200, Decimal("14.7850")),
    Fill("002414", date(2026, 8, 21), Side.BUY, 200, Decimal("13.8445")),
    Fill("601212", date(2026, 8, 21), Side.BUY, 200, Decimal("5.6108")),
)


def test_retrieve():
    """Executable example: the ledger reconciles against the real snapshot.

    The ledger is a fixed transcription of the broker screenshot, so this is
    the one test where the mark enters the arithmetic. Pinning `as_of` to
    2026-08-25 fixes which closes those marks are: refreshing the snapshot with
    newer bars cannot move a date in the past, which is why these numbers are
    reproducible rather than merely currently true.
    """

    as_of = date(2026, 8, 25)
    market = gather(as_of)
    portfolio = retrieve(market, as_of)

    # Cash, market value, and equity come out of the fills, not out of literals,
    # so this reconciliation is the check a hand-entered snapshot could skip.
    assert portfolio.cash == Decimal("500.00")
    # 47770 of holdings + 500 of cash, at the close of 2026-08-25.
    assert portfolio.value == Decimal("47770.00")
    assert portfolio.equity == Decimal("48270.00")
    # Decimal keeps the screenshot's cost basis exact, unlike binary floats.
    assert portfolio.position("000528").cost == Decimal("11.0715")
    # Every lot is dated 2026-08-21, so T+1 has long since passed.
    assert portfolio.position("000528").available(as_of) == 3000

    # A position's value is its own shares times the mark, so the total is not
    # a coincidence of the ledger but a check that both folds agree.
    assert portfolio.position("000528").value == 3000 * mark(market, "000528")
    assert portfolio.value == sum(position.value for position in portfolio.positions)

    # `as_of` is a filter, not decoration: the day before the buys, the account
    # is only the opening deposit.
    opening = retrieve(gather(date(2026, 8, 20)), date(2026, 8, 20))
    assert opening.positions == ()
    assert opening.cash == Decimal("56832.56")

    print("retrieve tests passed.")


if __name__ == "__main__":

    test_retrieve()
