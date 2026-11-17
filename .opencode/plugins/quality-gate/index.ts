import { Plugin } from "@opencode/plugin"
import { execFile } from "node:child_process"
import { existsSync } from "node:fs"
import path from "node:path"

type GateOptions = {
  script?: string
  gatedSubcommands?: string[]
  timeoutMs?: number
}

const GATED_BY_DEFAULT = ["commit", "push"]
// Options that consume the next word, so the subcommand is not mistaken for them.
const OPTIONS_WITH_VALUE = new Set([
  "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "-C", "-c",
])
const EXECUTION_WRAPPER = /(?:^|[\s;&|()])(?:bash|sh|zsh|dash|eval|xargs|env|sudo|nohup|command)\b/

/**
 * Reduce a raw shell command to the git subcommands it would run.
 *
 * The shell tool hands the plugin one string per invocation, so a compound
 * command is split here before the words are walked. Only the subcommand
 * matters; flags, paths and a leading `-c` are skipped.
 */
function gitSubcommands(command: string): string[] {
  const found: string[] = []
  for (const segment of command.split(/&&|\|\||[;|\n]/)) {
    const words = segment.trim().split(/\s+/).filter(Boolean)
    const index = words.findIndex((word) => word === "git" || word.endsWith("/git"))
    if (index === -1) continue
    let cursor = index + 1
    while (cursor < words.length) {
      const word = words[cursor]
      if (OPTIONS_WITH_VALUE.has(word)) {
        cursor += 2
        continue
      }
      if (word.startsWith("-")) {
        cursor += 1
        continue
      }
      found.push(word)
      break
    }
  }
  return found
}

/**
 * A conservative second opinion on the raw command text.
 *
 * A command hidden behind a wrapper such as `bash -c '...'` keeps its inner
 * words quoted, so the walk above cannot see `git` as a bare word. Running the
 * gate on a false positive only costs a test run, while missing a real commit
 * would defeat the gate, so wrapped text is matched on the raw string. The
 * wrapper test keeps a read-only search such as `grep -rn "git commit" docs`
 * cheap.
 */
function mentionsGatedGit(command: string, gated: Set<string>): boolean {
  if (!EXECUTION_WRAPPER.test(command)) return false
  for (const name of gated) {
    if (new RegExp(`(^|[^\\w-])git\\b[^\\n]*\\b${name}\\b`).test(command)) return true
  }
  return false
}

/**
 * The directory inside a git command that decides which repository it touches.
 *
 * `git -C <dir> commit` runs against another checkout while the shell stays in
 * the session directory, and `--work-tree` moves the index just as effectively.
 * Ignoring them would let a commit slip past the gate, so the last one wins, as
 * it does in git itself.
 */
/**
 * The directory inside a git command that decides which repository it touches.
 *
 * `git -C <dir> commit` runs against another checkout while the shell stays in
 * the session directory, `--work-tree` moves the index just as effectively, and
 * a leading `cd <dir> &&` moves the whole command. Ignoring them would judge the
 * wrong tree: a commit in a worktree would be checked against the tree the
 * session started in, so a red worktree could pass and a green one could block.
 * The last one wins, as it does in the shell and in git itself.
 */
function gitTarget(command: string): string | null {
  let directory: string | null = null
  for (const segment of command.split(/&&|\|\||[;|\n]/)) {
    const words = segment.trim().split(/\s+/).filter(Boolean)
    const unquoted = (word: string) => word.replace(/^['"]|['"]$/g, "")
    const change = words.findIndex((word) => word === "cd" && words.length > 1)
    if (change === 0) {
      const target = unquoted(words[1])
      if (target !== "-" && target !== "~") directory = target
    }
    const index = words.findIndex((word) => word === "git" || word.endsWith("/git"))
    if (index === -1) continue
    for (let cursor = index + 1; cursor < words.length - 1; cursor += 1) {
      if (words[cursor] === "-C" || words[cursor] === "--work-tree") {
        directory = unquoted(words[cursor + 1])
      }
    }
  }
  return directory
}

/** Run a command to completion and report whether it succeeded, with its output. */
function run(executable: string, args: string[], cwd: string, timeout: number) {
  return new Promise<{ ok: boolean; output: string }>((resolve) => {
    execFile(executable, args, { cwd, timeout, maxBuffer: 16 * 1024 * 1024 }, (error, stdout, stderr) => {
      resolve({ ok: !error, output: `${stdout}\n${stderr}`.trim() })
    })
  })
}

/**
 * The repository root a command would touch, or null when the directory is not
 * inside a repository.
 *
 * The gate belongs to the repository that owns it, and the shell tool accepts a
 * working directory, so a commit in a worktree has to be judged against that
 * worktree rather than the directory the session started in.
 */
async function repositoryRoot(directory: string): Promise<string | null> {
  const result = await run("git", ["rev-parse", "--show-toplevel"], directory, 30_000)
  if (!result.ok || !result.output) return null
  return result.output.split("\n")[0].trim() || null
}

export default Plugin.define({
  id: "quality-gate",
  async setup(ctx) {
    const options = ctx.options as GateOptions
    const gated = new Set(options.gatedSubcommands ?? GATED_BY_DEFAULT)
    const script = options.script ?? "scripts/quality-gate.sh"
    const timeout = options.timeoutMs ?? 1_800_000
    const fallbackDirectory = ctx.location.directory

    // A green gate describes one working tree at one moment. Nothing is cached,
    // so a green answer always comes from the files the commit would carry.
    const gate = async (directory: string, mode: string): Promise<string | null> => {
      const scriptPath = path.join(directory, script)
      if (!existsSync(scriptPath)) return null
      const result = await run("bash", [scriptPath, mode], directory, timeout)
      if (result.ok) return null
      return result.output.split("\n").slice(-40).join("\n")
    }

    // A push is the moment the result becomes public, so it also mirrors
    // docs/wiki into the wiki repository. A commit only owns tests and docs.
    const modeFor = (subcommands: string[]) =>
      subcommands.includes("push") ? "--push" : "--commit"

    /**
     * The shell tool is the only path that can run git, and this hook receives
     * the exact command plus its working directory, so the gate always watches
     * the tree the command would touch, including a worktree.
     */
    await ctx.tool.hook("execute.before", async (event) => {
      if (event.tool !== "shell") return
      const input = event.input as { command?: string; workdir?: string }
      const command = input.command ?? ""
      const subcommands = gitSubcommands(command)
      const intercepted =
        subcommands.some((name) => gated.has(name)) || mentionsGatedGit(command, gated)
      if (!intercepted) return
      // A `cd` or `-C` inside the command is written relative to the directory
      // the command starts in, so it is resolved against that, not the process.
      const start = input.workdir ?? fallbackDirectory
      const explicit = gitTarget(command)
      const target = explicit ? path.resolve(start, explicit) : start
      const root = await repositoryRoot(target)
      if (!root) return
      const failure = await gate(root, modeFor(subcommands))
      if (failure) {
        throw new Error(
          "quality-gate blocked this command: the tests and the documentation " +
            "checks must be green on the current tree first. Fix every item " +
            "below, then run the command again.\n\n" +
            failure,
        )
      }
    })

    // The git hooks are the same gate for the paths OpenCode does not see: a
    // human at the terminal, an IDE, a script. Installing them here keeps a
    // fresh clone covered without a manual setup step. An existing setting is
    // left alone, because a repository owner may have chosen another one.
    const root = await repositoryRoot(fallbackDirectory)
    if (root && existsSync(path.join(root, ".githooks", "pre-commit"))) {
      const configured = await run("git", ["config", "--get", "core.hooksPath"], root, 30_000)
      if (!configured.ok || !configured.output) {
        await run("git", ["config", "core.hooksPath", ".githooks"], root, 30_000)
      }
    }

    // The tool the model should reach for instead of guessing. It runs the same
    // script a human runs, so there is exactly one definition of green.
    await ctx.tool.transform((editor) => {
      editor.namespace({
        name: "quality_gate",
        description: "Quality gates for this repository",
      })
      editor.add({
        name: "verify",
        description:
          "Run the test suite and the documentation checks on the working tree. " +
          "Prints the gate report; a green report ends with 'gate: OK'.",
        input: { type: "object", properties: {}, additionalProperties: false },
        options: { namespace: "quality_gate", codemode: true },
        execute: async () => {
          const target = (await repositoryRoot(fallbackDirectory)) ?? fallbackDirectory
          const scriptPath = path.join(target, script)
          if (!existsSync(scriptPath)) return { content: `missing ${script} in ${target}` }
          const result = await run("bash", [scriptPath, "--commit"], target, timeout)
          return { content: result.output }
        },
      })
    })
  },
})
