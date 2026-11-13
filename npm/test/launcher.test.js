'use strict';

const assert = require('node:assert/strict');
const { spawn, spawnSync } = require('node:child_process');
const { mkdirSync, readFileSync, rmSync, writeFileSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join, resolve } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const launcher = resolve(__dirname, '../bin/tapebasis.js');
const directories = new Set();

const source = readFileSync(launcher, 'utf8').replace(/\nmain\(\);\s*$/, `
  module.exports = { executable, forwardSignal, main };
`);

/**
 * Load the launcher's testable functions without starting an MCP child process.
 * @returns {{executable: Function, forwardSignal: Function}} Launch and signal helpers.
 */
function launcherFunctions() {
  const context = { module: { exports: {} }, require, process, console };
  vm.runInNewContext(source, context, { filename: launcher });
  return context.module.exports;
}

/**
 * Create an isolated fake uvx executable and a log of its received process state.
 * @param {object} t The active Node test context, used for cleanup.
 * @returns {{executable: string, logFile: string}} Fixture paths for a spawned child.
 */
function fakeUvx(t) {
  const dir = join(tmpdir(), `tapebasis-npm-${process.pid}-${directories.size}`);
  directories.add(dir);
  mkdirSync(dir, { recursive: true });
  t.after(() => {
    rmSync(dir, { recursive: true, force: true });
    directories.delete(dir);
  });
  const executable = join(dir, 'fake-uvx.js');
  const logFile = join(dir, 'events.jsonl');
  writeFileSync(executable, `#!${process.execPath}\nconst fs = require('node:fs');\nconst log = (event) => fs.appendFileSync(${JSON.stringify(logFile)}, JSON.stringify(event) + '\\n');\nlog({args: process.argv.slice(2), env: {MARK: process.env.MARK, WITH_SPACE: process.env.WITH_SPACE}});\nif (process.env.TEST_SIGNAL) { process.on('SIGTERM', () => { log({signal: 'SIGTERM'}); process.exit(0); }); setInterval(() => {}, 1000); } else { process.exit(Number(process.env.EXIT_CODE || 0)); }\n`, { mode: 0o755 });
  return { executable, logFile };
}

/**
 * Return a copy of the current environment with test-specific overrides applied.
 * @param {object} extra Variables that replace inherited variables.
 * @returns {object} The environment passed to a child process.
 */
function env(extra = {}) {
  return { ...process.env, ...extra };
}

test('forwards args and env exactly, including spaces and dollar signs', async (t) => {
  const { executable, logFile } = fakeUvx(t);
  const result = spawnSync(process.execPath, [launcher, 'argument with spaces', '$(echo nope)'], {
    env: env({ TAPEBASIS_UVX: executable, MARK: 'forwarded', WITH_SPACE: 'kept' }),
    encoding: 'utf8',
  });
  assert.equal(result.status, 0, result.stderr);
  const record = JSON.parse(readFileSync(logFile, 'utf8').split('\n')[0]);
  assert.deepEqual(record.args, ['tapebasis', 'argument with spaces', '$(echo nope)']);
  assert.equal(record.env.MARK, 'forwarded');
  assert.equal(record.env.WITH_SPACE, 'kept');
});

test('default uvx has no runtime credentials and exits with child status', async (t) => {
  const { executable, logFile } = fakeUvx(t);
  const result = spawnSync(process.execPath, [launcher], {
    env: env({ TAPEBASIS_UVX: executable, EXIT_CODE: '23' }),
    encoding: 'utf8',
  });
  assert.equal(result.status, 23);
  const record = JSON.parse(readFileSync(logFile, 'utf8').split('\n')[0]);
  assert.deepEqual(record.args, ['tapebasis']);
  assert.equal(process.env.UV_PUBLISH_TOKEN, undefined);
});

test('Windows resolves uv.exe and never needs a command shell', (t) => {
  const { executable } = launcherFunctions();
  const dir = join(tmpdir(), `tapebasis-windows-${process.pid}`);
  mkdirSync(dir, { recursive: true });
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  writeFileSync(join(dir, 'uv.exe'), 'test fixture');
  const selected = executable({ Path: dir }, 'win32');
  assert.equal(selected.command, join(dir, 'uv.exe'));
  assert.deepEqual(Array.from(selected.args), ['tool', 'run', 'tapebasis']);
  const fallback = executable({ Path: '' }, 'win32');
  assert.equal(fallback.command, 'uvx.exe');
  assert.deepEqual(Array.from(fallback.args), ['tapebasis']);
});

test('missing uv explains how to install it', () => {
  const result = spawnSync(process.execPath, [launcher], {
    env: { PATH: '' },
    encoding: 'utf8',
  });
  assert.equal(result.status, 127);
  assert.match(result.stderr, /uv is required/);
  assert.match(result.stderr, /https:\/\/docs\.astral\.sh\/uv\/getting-started\/installation\//);
  assert.doesNotMatch(result.stderr, /undefined/);
});

test('SIGTERM is forwarded to the child process and its status is propagated', async (t) => {
  const { executable, logFile } = fakeUvx(t);
  const child = spawn(process.execPath, [launcher], {
    env: env({ TAPEBASIS_UVX: executable, TEST_SIGNAL: 'yes' }),
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  await new Promise((resolve) => {
    const check = () => {
      try {
        if (readFileSync(logFile, 'utf8')) return resolve();
      } catch { /* Wait for the child to start. */ }
      setTimeout(check, 10);
    };
    check();
  });
  child.kill('SIGTERM');
  const [code, signal] = await new Promise((resolve) => child.on('exit', (...args) => resolve(args)));
  const events = readFileSync(logFile, 'utf8').trim().split('\n').map(JSON.parse);
  assert.ok(events.some(event => event.signal === 'SIGTERM'));
  assert.equal(code, process.platform === 'win32' ? 0 : 143);
  assert.equal(signal, null);
});

test('launcher has no third-party dependencies', () => {
  const manifest = JSON.parse(readFileSync(require('node:path').resolve(__dirname, '../../package.json')));
  assert.equal(manifest.dependencies, undefined);
  assert.equal(manifest.devDependencies, undefined);
  const server = JSON.parse(readFileSync(require('node:path').resolve(__dirname, '../../server.json'), 'utf8')).name;
  assert.match(server, /io\.github\./);
});
