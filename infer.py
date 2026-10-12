"""Infer: turn market observations into beliefs.

Step four of the plan, the modelling layer. The decision layer may only see
`Belief`, never the raw market, and holding that belief to two fields is the
whole discipline of the step.

The current model is naive momentum -- the return over the observed window --
i.e. "the recent past repeats". It is deliberately dumb, but structurally
real: one number per name, computed from the market and nothing else. A
managerie of strategies can be freely selected and combined later, as long as
they all reduce to a `Belief`. Swap the body, keep the signature.
"""

from dataclasses import dataclass, fields
from decimal import Decimal

from gather import Instrument, Market, Price, history


@dataclass(frozen=True)
class Belief:
    """The posterior summary the decision layer is allowed to see.

    Keeping this to two fields is the whole discipline of the inference
    layer: `rebalance` cannot peek at raw prices, only at this.
    """

    symbol: str
    expected_return: Price              # over the window in `closes`


type Beliefs = dict[str, Belief]        # symbol -> belief


def infer(market: Market) -> Beliefs:
    """Extract investment signals from the collected market information,
    together with all investment principles, modeling assumptions, etc.

    Currently just naive momentum: the return over the observed window.
    """
    return {
        symbol: Belief(symbol, instrument.closes[-1] / instrument.closes[0] - 1)
        for symbol, instrument in market.items()
    }


def test_infer():
    """Executable example: momentum is signed, and nothing else leaks."""

    beliefs = infer({
        "UP": Instrument("UP", "Up", history("10.00", "11.00")),
        "DOWN": Instrument("DOWN", "Down", history("10.00", "9.00")),
    })

    assert beliefs["UP"].expected_return == Decimal("0.1")
    assert beliefs["DOWN"].expected_return == Decimal("-0.1")
    # The decision layer sees exactly these two fields and nothing else.
    assert [field.name for field in fields(beliefs["UP"])] == \
        ["symbol", "expected_return"]

    print("infer tests passed.")


if __name__ == "__main__":

    test_infer()
