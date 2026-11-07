# Agent instructions for coding tasks

## project

A research-first, risk-aware trading system for Chinese A-shares. Python scripts are the source of truth for implementation and runnable examples; `trade.org` holds background, design reasoning, and research. Execution is manual: a session ends with a ticket that a human places by hand.

Current status: **Fresh restart.** Treat the scripts listed below as the current implementation baseline. The main workflow and some planned modules still need to be built.

The session flow is specified by the `<<wish-trade>>` block under `* wishful plan` in `trade.org`. It is a design sketch, not executable implementation.

## commands

Run from this folder with the local virtual environment at `.venv`:

- Run a module and its examples: `.venv/bin/python <module>.py`. `watches.py` has no `__main__`; check it with `.venv/bin/python -c 'import watches'`.
- `source.py` runs its live endpoint checks with no arguments. Use `.venv/bin/python source.py refresh [symbol ...]` to deliberately update saved market data; no symbol means the whole watchlist.
- Modules other than `source.py` read the local snapshot in `bars/`. Do not refresh data unless the user asks.

## current modules

- `watches.py` — watchlist.
- `source.py` — the only network-facing module; fetches and writes market snapshots.
- `market.py` — point-in-time market data; `gather()` omits symbols with no bars by `as_of`.
- `account.py` — account and ledger; `LEDGER` is the current account history.
- `inference.py` — beliefs from the market snapshot.
- `orders.py` — rebalance rules and manual order intentions.

Planned work:

- `trade.py` — currently a placeholder; implement the session flow from `<<wish-trade>>` and thread one `as_of` through each step.
- `report.py` — not implemented; produce the risk picture and human-facing ticket.
- Backtest driver — not implemented; replay a ledger against historical `gather(as_of)` data.

Nothing in the `gather → replay → signal → orders → ticket` path may call the network or use `source.py`.

## source and design notes

Python modules hold the implementation and runnable examples. `trade.org` holds design logic and research, not duplicate implementations or runnable examples. The only source block retained there is the non-executable `wish-trade` flow sketch.

To locate a definition, search the Python files, for example `rg '^def replay' .`. To find design reasoning, search `trade.org`. The Org headings provide its outline: `grep -n '^\* ' trade.org`.

Data lives outside the code: `bars/raw/` and `bars/qfq/` hold one CSV per symbol (unadjusted / 前复权), and `bars/names.csv` holds names. Only `source.py` writes them; everything else reads.

## script conventions

- Order definitions by dependency. Keep imports and types before functions that use them, so the script reads top to bottom.
- Keep explanations close to the code. Use brief comments and one-line docstrings for local intent; put longer design reasoning in `trade.org`.
- Keep examples small and offline by default. Each module's `test()` should be a runnable demonstration under `if __name__ == "__main__":`. The deliberate exception is `source.py`, whose no-argument checks call live endpoints and write only to temporary test directories.
- Use exact `==` for quantities, cash, and marked values that are integer sums. Use `math.isclose` for divided values such as cost per share, weights, and returns.

## working with the human

This is a human-in-the-loop project. The human owns the design and development direction.

- Check for the human's latest edits before each step and preserve them.
- Work on one agreed task at a time. Make the smallest coherent change, then explain what changed, why, and how it was checked.
- Do not silently expand the task into later modules, broad rewrites, or speculative architecture. Discuss consequential design choices; use judgment for routine implementation details.
- Keep reasoning visible in plain language. Aim for concise code, clear logic, and edge cases that fail loudly.
- Build gradually so the human can review and steer the work.
