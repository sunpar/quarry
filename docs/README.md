# Docs

How Quarry's docs are organized and when each one changes. To resume work, start
with [working-state.md](working-state.md).

## Temporary context

Temporary context is true today and stale soon: what is in flight, current test
results, the next experiment, a live debugging hypothesis.

| File                                 | Holds                                                                                     | Update                                                                      |
| ------------------------------------ | ----------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| [working-state.md](working-state.md) | Current objective, status by stage, open pull requests, latest verification, next actions | Rewrite at the end of each session, and when a pull request opens or merges |

## Backlog

| File                           | Holds                                                      | Update                                                                                                                         |
| ------------------------------ | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| [open-items.md](open-items.md) | Known problems, deferred work by stage, and open questions | When an item is found, deferred or resolved. Delete resolved items, and move an answered question into decisions as a decision |

## Permanent context

Permanent context stays true across sessions: architecture decisions,
definitions and constraints.

| File                                             | Holds                                                                                  | Update                                                                   |
| ------------------------------------------------ | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| [context/constraints.md](context/constraints.md) | Facts Quarry cannot change: authority, product rules, environment, gates               | Rarely: when the spec or the environment changes                         |
| [context/decisions.md](context/decisions.md)     | Choices made where the spec was silent or wrong, with the reason and the cost if wrong | When a decision is made. Rewrite an entry that a later decision reverses |
| [context/glossary.md](context/glossary.md)       | Terms used in code and docs                                                            | When a new term appears                                                  |
| [context/code-map.md](context/code-map.md)       | Each module's responsibility, spec section and tests                                   | When a module is added, moved or removed                                 |

## Design and plans

| File                                                                                           | Holds                             | Update                                                |
| ---------------------------------------------------------------------------------------------- | --------------------------------- | ----------------------------------------------------- |
| [superpowers/specs/2026-10-08-quarry-design.md](superpowers/specs/2026-10-08-quarry-design.md) | The binding design                | Amend when a decision departs from it                 |
| [superpowers/plans/](superpowers/plans/)                                                       | One implementation plan per stage | Written before a stage starts. History once it starts |

## Rules for these docs

- Each fact lives in one file. Link to it instead of repeating it.
- Permanent docs say what is true now. Git keeps the history, so rewrite an
  entry rather than appending a correction.
- Test counts, branch names and hypotheses go in the working state, never in
  permanent docs.
- Keep entries short: one bullet per decision or item, with the reason in a
  sentence.
- Wrap prose at 80 columns with
  `npx prettier --prose-wrap always --write <file>`. The full `.verify.toml`
  gate checks formatting.
