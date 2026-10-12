"""Evaluate: the risk picture the current positions imply.

Step three of the plan. Deliberately thin -- a static read of the constraints
`Portfolio` already enforces -- and `Metrics` is the entire vocabulary the
human sees before deciding anything.

TODO extend to the whole performance eval of all investment to date: realised
vs unrealised P&L, drawdown, attribution, and the equity curve over time.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from gather import Price
from portfolio import Lot, Portfolio, Position


@dataclass(frozen=True)
class Metrics:
    """The risk picture `evaluate` hands to the human."""

    equity: Price
    cash_weight: Decimal
    max_weight: Decimal
    issues: tuple[str, ...]


def evaluate(portfolio: Portfolio) -> Metrics:
    """Report the numbers the risk constraints actually care about.
    currently simply a static analysis of the current holdings.
    """
    return Metrics(
        equity=portfolio.equity,
        cash_weight=portfolio.cash_weight,
        # `default` is not defensiveness: an account holding only cash is a
        # real state, and max() over an empty sequence would raise on it.
        max_weight=max((portfolio.weight(p.symbol) for p in portfolio.positions),
                       default=Decimal("0")),
        issues=tuple(portfolio.issues()),
    )


def test_evaluate():
    """Executable example: the numbers and the warnings agree."""

    portfolio = Portfolio(
        cash=Decimal("20000"),
        positions=(Position("X", "Ex",
                            (Lot(date(2026, 8, 21), 3000, Decimal("8.0")),),
                            Decimal("10.0")),),
    )
    metrics = evaluate(portfolio)

    assert metrics.equity == Decimal("50000")
    assert metrics.cash_weight == Decimal("0.4")
    assert metrics.max_weight == Decimal("0.6")
    assert metrics.issues == ("Ex(X) is overweight",)
    # An emptied account is a state to describe, not a division error.
    assert evaluate(Portfolio(Decimal("0"), ())).cash_weight == Decimal("0")

    print("evaluate tests passed.")


if __name__ == "__main__":

    test_evaluate()
