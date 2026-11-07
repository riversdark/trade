"""Extract trading singles from market.

Belief is the return type of the infer engine.
In time this module should be heavily AI agent driven.

Possible ideas to incorporate:
    - volatility modeling.
    - US market monitoring
    - sentiment analysis
"""
from dataclasses import dataclass
from datetime import date
from math import isclose

from market import Instrument, Market, gather

@dataclass(frozen=True)
class Belief:
    """A return estimate and current raw price for one instrument."""

    expected_return: float
    mark: float

type Beliefs = dict[str, Belief]

def momentum_belief(inst: Instrument) -> Belief:
    """Estimate return from the first to last adjusted close.
    this is a placeholder belief method.
    """
    closes = inst.adjusted_closes
    return Belief(closes[-1] / closes[0] - 1, inst.closes[-1])

def infer(mkt: Market) -> Beliefs:
    """Infer investment beliefs for Market object.
    for the moment, focusing on simple per instrument inference.
    a joint modeling approach is possible.
    """
    beliefs = {}
    for symbol, inst in mkt.items():
        if not inst.adjusted_closes:
            print(f"Skipping {symbol}: no adjusted closes.")
            continue
        beliefs[symbol] = momentum_belief(inst)
    return beliefs

def test():
    """Show momentum beliefs inferred from the local market snapshot."""
    mkt = gather(date(2026, 8, 25), 60)
    beliefs = infer(mkt)
    assert set(beliefs) <= set(mkt)

    for symbol, belief in beliefs.items():
        closes = mkt[symbol].adjusted_closes
        assert isclose(belief.expected_return, closes[-1] / closes[0] - 1)
        assert belief.mark == mkt[symbol].closes[-1]
        print(symbol, belief.expected_return)

    print("\nInfer tests passed.")

if __name__ == "__main__":

    test()
