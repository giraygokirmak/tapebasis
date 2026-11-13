---
name: Quality Gate
description: Definition of done for a code change in this repository: run the tests, sync the documentation repo-wide, then commit and push. Use before finishing any edit, and whenever the quality gate blocks a commit.
---

# Quality Gate

A change is not done when the code compiles. It is done when the tests are green,
the documentation describes what the code now does, and the wiki carries the same
pages, all of it landed together.

The gate enforces that mechanically. Everything below is the order that keeps it
green on the first attempt.

## Definition of done

1. **Tests first, not after prompting.** The moment a source file changes, run
   `scripts/quality-gate.sh --tests-only`. Do not wait to be asked. A red suite
   is the current task, not a follow-up.
2. **Documentation in the same batch.** Before the commit, run
   `scripts/quality-gate.sh --docs-only` and fix every finding. Documentation is
   part of the change, not a second change.
3. **One green run, then commit.** `scripts/quality-gate.sh --commit` runs both
   halves. Only when it ends with `gate: OK` may `git commit` run.
4. **Push publishes the wiki.** `git push` runs the gate again, and this time it
   also mirrors `docs/wiki/` into the GitHub wiki, so the published pages never
   lag behind the repository.
5. **Never split the batch.** Do not commit code now and documents later. The
   gate blocks the commit, and a separate documentation commit ships a stale
   contract in the first one.

## What the gate runs

| Layer | Command | Blocks on |
| --- | --- | --- |
| Tests | `pytest -q` | Any failing or erroring test, collection errors included |
| Documentation | `python scripts/quality_gate.py` | See `references/checks.md` |
| Wiki mirror | `scripts/publish-wiki.sh` | Uncommitted pages, or a failed publish |

The gate is a plugin plus a pair of git hooks, not a suggestion. The plugin
intercepts `git commit` and `git push` from the shell tool; the hooks cover every
path OpenCode does not see. Nothing is cached, so a green result always describes
the exact files the commit would carry.

## When the gate blocks

Read the report it returns, then fix in this order: undocumented function, then
stale documentation claim, then formatting rules. The report names the file and
the line; it never asks a question.

Do not retry the same command. Do not look for a way around the gate, and do not
disable it. A blocked commit means the work is not finished yet.

## Writing the documentation

- Every function and method you add gets a docstring that states what it returns
  or what it changes, not what its name already says.
- A new tool appears in `README.md` and in `docs/wiki/Tools-Reference.md`, with
  its provider set spelled out.
- A changed contract means checking the wiki pages that describe it. The record
  of a decision lives in `docs/wiki/Design-Decisions.md`.
- A changed public signature needs its documentation in the same commit.

## House rules the checks encode

- No em dash anywhere in prose, docstrings, or free text.
- Say "multiple providers" or "every provider", never a count of sources.
- Relative wiki links must resolve, including their fragments.

See `references/checks.md` for each check, why it exists, and the exact fix.
