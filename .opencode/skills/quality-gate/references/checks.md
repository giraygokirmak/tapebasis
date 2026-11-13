# Gate checks

`scripts/quality_gate.py` prints a JSON report and exits non-zero when any list
is non-empty. Each check is independent, so one failure never hides another.

## `undocumented`

Every function and method in `src/tapebasis/` carries a docstring, except for the
entries in `scripts/quality_gate_baseline.json`.

The baseline is frozen debt: the access layer and the vendored provider clients
predate this gate. A function that is undocumented and **not** in the baseline is
new debt and fails the check. That is the whole rule: written today means
documented today.

Fix: add a docstring. Say what the function returns, raises, or changes; do not
restate its name.

## `stale-baseline`

An entry in the baseline that is documented now fails the check.

Without this, the baseline would silently absorb documentation you just wrote and
the list would never shrink. The fix is the point: delete the entry from
`scripts/quality_gate_baseline.json`, so the baseline records only real debt and
only ever gets shorter.

## `em-dash`

No em dash in any tracked text file: Markdown, Python, TOML, JSON, YAML, shell.

The repository's prose is published in the README, the wiki, and MCP responses.
The em dash is the one character that renders differently across those surfaces,
so it is banned outright rather than normalized.

Fix: rewrite the sentence with a comma, a colon, parentheses, or two sentences.

## `wiki-links`

Every relative link in `docs/wiki/*.md` resolves to a page that exists, and every
`#fragment` resolves to a heading in that page.

The wiki is mirrored byte for byte into the GitHub wiki repository, where a
broken relative link is a dead end. Fragments are checked because a renamed
heading breaks every anchor pointing at it, and headings get renamed often.

Fix: point the link at an existing page, or rename the heading back.

## `doc-with-code`

A module whose public surface changed must be accompanied by a documentation
change in the same batch.

The rule is one batch: the commit that changes the contract is the commit that
updates it. Only the public surface counts, so an internal refactor, a docstring
rewrite or a fix inside a body needs no docs edit, while a new or reshaped
function does. A brand-new module is exempt here because the `undocumented`
check already covers it.

Fix: update the wiki page or the README section that describes the module.

## `tool-coverage`

Every tool registered on the FastMCP server is named in backticks in both
`README.md` and `docs/wiki/Tools-Reference.md`.

The tool surface is the product. A tool nobody documents does not exist for a
user reading the contract.

Fix: add the tool to both documents in the same edit as the code.

## `tool-count`

Every integer followed by the word "tools" in `README.md`,
`docs/wiki/Home.md`, `docs/wiki/Getting-Started.md`, and
`docs/wiki/Tools-Reference.md` matches the number of registered tools.

Counts drift the moment a tool is added, and a wrong count is a wrong claim about
the product. Fix: update the number, or remove it in favor of "every tool".

## Why the gate is a plugin and a hook

Skills are advisory: they are instructions the model may follow. Permissions and
policies can block an action but cannot run a command. Only a plugin hook can run
the checks and then decide.

The plugin registers one `execute.before` hook for `shell`. It parses the command
for a `git commit` or `git push` subcommand, resolves the repository the command
would touch (`workdir`, `git -C`), runs `scripts/quality-gate.sh` there, and
throws when anything is red.

The git hooks in `.githooks/` run the same script for everything OpenCode does not
see: a terminal, an IDE, a script. The plugin installs `core.hooksPath` on setup
when the repository has no setting of its own.

## Running it by hand

```bash
scripts/quality-gate.sh              # tests, documentation and the wiki mirror
scripts/quality-gate.sh --commit     # tests and documentation only
scripts/quality-gate.sh --push       # tests, documentation and the wiki mirror
scripts/quality-gate.sh --tests-only
scripts/quality-gate.sh --docs-only
python scripts/quality_gate.py       # documentation only, JSON report
```

Set `TAPEBASIS_PYTHON` when the environment that owns the dependencies is not
`.venv/bin/python`.
