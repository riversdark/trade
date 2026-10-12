"""Render: the ticket to place by hand.

Step six, the last one of the plan. The program's whole product is something a
human reads and acts on, so `render` is not a debug printer: it is the
interface.

`pad` exists because the names are Chinese. `f"{text:<8}"` counts code points,
so CJK names come out ragged in every terminal; `unicodedata.east_asian_width`
is the standard answer, with 'W' (wide) and 'F' (fullwidth) glyphs occupying
two cells.
"""

import unicodedata
from decimal import Decimal

from portfolio import Side
from rebalance import Order


def pad(text: str, width: int) -> str:
    """Left-justify to a *display* width, counting CJK glyphs as two columns."""

    shown = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * (width - shown)


def render(orders: list[Order]) -> str:
    """The ticket: what to place, and why."""
    lines = [
        f"{o.side.value.upper():<4} {o.symbol} {pad(o.name, 10)} {o.quantity:>6,d}"
        f" @ {o.price:,.3f} = {o.value:>12,.2f}   {o.reason}"
        for o in orders
    ]
    buys = sum((o.value for o in orders if o.side is Side.BUY), Decimal("0"))
    sells = sum((o.value for o in orders if o.side is Side.SELL), Decimal("0"))
    lines.append(f"{len(orders)} orders | sell {sells:,.2f} | "
                 f"buy {buys:,.2f} | net {sells - buys:,.2f}")
    return "\n".join(lines)


def test_render():
    """Executable examples: CJK alignment and the netting line."""

    ticket = render([Order("000528", "柳工", Side.SELL, 1600, Decimal("8.040"),
                           "overweight 51.2%")])

    # Two wide glyphs occupy four cells, so six spaces complete a width of ten.
    assert pad("柳工", 10) == "柳工" + " " * 6
    assert pad("AB", 10) == "AB" + " " * 8
    assert "SELL 000528" in ticket
    assert "1,600" in ticket
    assert ticket.splitlines()[-1] == \
        "1 orders | sell 12,864.00 | buy 0.00 | net 12,864.00"

    print("render tests passed.")


if __name__ == "__main__":

    test_render()
