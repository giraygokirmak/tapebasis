# Repository instructions

## Definition of done

A change is finished only when the tests are green and the documentation
describes the new behaviour, in one batch, before the commit.

1. After changing any file under `src/`, run `scripts/quality-gate.sh --tests-only`.
   Do not wait to be asked.
2. Before committing, run `scripts/quality-gate.sh --commit` and fix every
   finding.
3. Commit only when it prints `gate: OK`, then push.
4. Never split a change into code now and documentation later.

A plugin enforces this mechanically: it intercepts `git commit` and `git push`,
runs the gate against the working tree, and denies the command while anything is
red. Do not look for a way around it. A blocked commit means the work is not
finished.

## Documentation rules

- Every function or method you add carries a docstring that says what it returns
  or changes.
- A new tool appears in `README.md` and `docs/wiki/Tools-Reference.md` in the
  same edit as the code.
- A changed contract means checking the wiki pages that describe it; a new
  decision belongs in `docs/wiki/Design-Decisions.md`.
- The docs are one body of work, not per-file afterthoughts: when a contract
  changes, sweep every page that states it in the same batch, run
  `scripts/quality-gate.sh --docs-only`, then commit.
- A push publishes `docs/wiki/` to the GitHub wiki; the gate does it for you.
- No em dash in prose, docstrings, or free text.
- Say "multiple providers" or "every provider", never a count of sources.
- `README.md` carries no Documentation section.

## Environment

`scripts/quality-gate.sh` picks `.venv/bin/python`, then `venv/bin/python`, then
`python3`. Set `TAPEBASIS_PYTHON` when the environment holding the dependencies
lives elsewhere.
