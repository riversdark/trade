# Agent instructions for coding tasks

## what this is

A research-first, risk-aware trading system for Chinese A-shares, built as literate programming in `trade.org`. The org file is the single source of truth; every `.py` module here is tangled output from it. Execution is manual: a session ends with a ticket that a human places by hand.

The whole workflow is one session and each step is one function in one module — the spec is block `<<wish-trade>>` under `* wishful plan`.

## commands

Run from this folder, using the repo-root venv (`source ../../.venv/bin/activate`, or call `../../.venv/bin/python` directly):

- Tangle after every org edit: `emacs --batch trade.org --eval '(org-babel-tangle)'` (or `C-c C-v t` from the buffer).
- Check a module: `python <module>.py`. The new modules (`book`, `market`, `watches`) have no `__main__`, so this is an import check and must exit 0; the old modules run their offline self-test under `__main__`.
- Name-collision check after adding any named block: `grep -o '^#+name: .*' trade.org | sort | uniq -d` — must print nothing.
- Refresh market data, deliberately (the only network step): `python source.py refresh [symbol ...]`; no symbol means the whole watchlist. Everything else reads the local snapshot in `bars/`.

## finding your way in `trade.org`

The file is ordered by the dependency tree: background → wishful plan → watches → market → account → beliefs/orders/evaluations → session orchestration/backtesting, then research notes. Each module section ends with one assembly block whose `<<fragment>>` references are that module's table of contents in export order; fragment names follow `<module>-<thing>`.

| module | where it lives in trade.org | state |
|---|---|---|
| `watches.py` | `* watches` | done |
| `source.py` | `* market` → `** source` | done; the only network-facing module, CLI is `refresh` |
| `market.py` | `* market` → `** gather: market information`; assembly in `** assembling the module` | done — except `<<market-history>>`, which is named and run but not referenced by the assembly block, so `history()` is missing from the module |
| `book.py` | `* account` → `** the account`, `** the ledger`, `** replay the ledger into account`; assembly in `** next steps` | done; numbers verified against old `ledger` + `portfolio` |
| `decide.py` | planned: rewrite of `* beliefs` → `** infer` + `** rebalance`. Takes `Rules` explicitly, returns signals and orders, never touches the account's policy fields | not started |
| `report.py` | planned: rewrite of `* evaluations` (+ `** render: the ticket`) — the risk picture first, then the human-facing ticket | not started |
| `trade.py` (new) | planned: `* session orchestration`; spec is `<<wish-trade>>` under `* wishful plan`. Threads one `as_of` through every step | not started |
| backtest driver | `* backtesting`: replay a ledger against historical `gather(as_of)` data | not started |

The old modules (`gather`, `ledger`, `portfolio`, `retrieve`, `evaluate`, `infer`, `rebalance`, `render`, and the current `trade.py`) are the reference implementation: their numbers are what each rewrite must reproduce. They stay in place until every replacement lands; retirement is one batch, and nothing in the `gather → replay → signal → orders → ticket` path may import them or touch `source.py`. The real account history (`LEDGER`) currently lives in `retrieve.py` until persistence replaces it.

Jump recipes — headings and names are stable, line numbers go stale:

- Which section owns a module? `grep -n ':tangle <file>' trade.org`; the nearest `^* ` heading above is the section.
- Where is a definition? `rg '^def replay' trade.org`, or search for its fragment name (`<<book-replay>>`).
- What does it print on real data? The `#+RESULTS:` blocks in the section — examples are never tangled, so those numbers live only in the org file.
- Current outline: `grep -n '^\(\* \|\*\* \)' trade.org`.

Data lives outside the code: `bars/raw/` and `bars/qfq/` hold one CSV per symbol (unadjusted / 前复权), `bars/names.csv` holds names. Only `source.py` writes them; everything else reads.

## general principles

This is a human-in-the-loop project, the building process is also a learning process.
- check file updates before each step, because the human in the loop will also be constantly updating them.
- aim for incremental edits rather than wholesale rewrites, easier for the human to keep track of changes.
- proceed in small, verifiable steps, let the human understand each new functionality before moving on.
- aim for concise code and clear logic, don't write overly defensive code, let edge cases fail loudly.
- note new packages/functionalities, noteworthy programming patterns, etc, so I can continuously improve my skills.
- build up gradually, don't add too much complexity at once.
- each agent action should focus on one and only one task
- the first solution will never be the best one, because we make overall plans at the start and work out the details later; that's alright, because refactoring is inherently part of programming

## the section format

Tests are written in the same file, alongside the code, so that they both serve as tests and runnable examples; they are often collected from interaction exploration, and they stay offline — nothing in them reaches the network.

Every module section follows this shape. It was worked out on `book` and is the contract for the ones after it.

- **Definitions are ordered by the dependence tree**, and each section states that tree at its head — `CashFlow + (Side -> Fill) -> Entry -> Ledger`. A block may use only what is already defined above it, so the exported file imports cleanly and reads bottom-up without forward references.
- **Every definition is validated immediately after it appears.** The example is part of the explanation, not a chore deferred to the end, which is exactly why the work happens in an interactive language. It runs in the module's session, so the variables it binds stay live for the examples below.
- **Examples are not tangled.** Only the assembly block at the end of the section carries `:tangle <module>.py`, so examples never reach the module and `python <module>.py` does not run them. The tests are done by hand, in the org file.
- **Docstrings are one line.** Anything longer is prose, in the section, where it can be read as an argument. A one-line summary survives in the tangled file and in `help()`, which is all a docstring is for.
- **No machinery.** There is no test framework, no `check_` functions, and no runner. An example is a few lines that assert and print what they saw. Because the session carries state forward, a later example reuses an earlier variable instead of rebuilding a thin fixture of its own.
- **Float exactness is split deliberately.** Exact `==` for quantities, cash, and marked value, which are integer sums; `math.isclose` for anything divided — cost per share, weights, returns — because those are correctly rounded but not exactly representable.

## the tangle contract

`trade.org` is the source. The `.py` modules are generated from it and are tracked only so they can be read next to the prose; never edit one by hand, because the next tangle overwrites it.

Each section ends with one assembly block that lists its definitions as `<<noweb>>` references, in export order. That is the mechanism that lets literate order differ from export order:

```
# one block per section, at the end, is the only thing that tangles
#+begin_src python :tangle book.py :noweb tangle
<<book-import>>
...
#+end_src

# a definition elsewhere in the section, named as <<reference-name>> and not
# tangled on its own
#+begin_src python
...
#+end_src
```

```
:PROPERTIES:
:header-args:python: :tangle no :mkdirp yes
:END:

C-c C-v t          # org-babel-tangle, from this buffer
emacs --batch trade.org --eval '(org-babel-tangle)'   # headless
```

Two properties make that safe, and the file-level default is the important one:

- `:header-args:python: :tangle no :mkdirp yes` lives in trade.org's property drawer. `:tangle no` means a snippet tangles **only** when it names a file, so a teaching fragment that happens to be valid Python cannot silently become a module. `:mkdirp yes` creates the directory if a path needs one.
- `:tangle book.py :noweb tangle` on the assembly block is what actually produces output.

Because noweb resolves **by name**, two blocks sharing a `#+name:` are silently resolved to the first one, and a definition disappears from the module while the tangle still reports success. This bit us once already: an illustration inside a `#+begin_example` block shared the name `book-money` with the real definition, and org happily used the illustration. Example blocks are part of the same namespace, so a fragment meant to be read, not run, must not be named. Two habits keep it honest:

```
grep -o '^#+name: .*' trade.org | sort | uniq -d    # must print nothing
python <module>.py                                  # must import and run
```

One trap, verified on Emacs 30.2 rather than assumed:

- The subtree form `:tangle book.py :comments no` is **not** what it looks like: org reads everything after the filename as part of the filename and writes a file literally named `book.py :comments no`. Keep the block header to a plain path and put the rest in a property.
