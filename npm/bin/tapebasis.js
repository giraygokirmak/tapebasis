#!/usr/bin/env node
'use strict';

const { spawn } = require('node:child_process');
const { constants } = require('node:os');
const { statSync } = require('node:fs');
const { delimiter, join } = require('node:path');

/**
 * Resolve the uv executable. On Windows prefer uv.exe so arguments are never
 * reinterpreted by a command shell, then fall back to the uvx executable.
 * @returns {{command: string, args: string[]}} The executable and initial arguments.
 */
function executable(environ = process.env, platform = process.platform) {
  if (environ.TAPEBASIS_UVX) {
    return { command: environ.TAPEBASIS_UVX, args: ['tapebasis'] };
  }

  if (platform === 'win32') {
    const pathValue = environ.Path || environ.PATH || '';
    for (const directory of pathValue.split(delimiter)) {
      if (!directory) continue;
      const candidate = join(directory, 'uv.exe');
      try {
        if (statSync(candidate).isFile()) {
          return { command: candidate, args: ['tool', 'run', 'tapebasis'] };
        }
      } catch {
        // Try the next PATH entry.
      }
    }
  }

  return { command: platform === 'win32' ? 'uvx.exe' : 'uvx', args: ['tapebasis'] };
}

/**
 * Terminate the direct child without terminating the MCP client's process.
 * The child is created in its own process group on POSIX, so forwarding to the
 * negative PID reaches uvx and the MCP server together after uvx has started it.
 * @param {import('node:child_process').ChildProcess} child The child process to stop.
 * @param {NodeJS.Signals} signal The signal to forward.
 */
function forwardSignal(child, signal) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  try {
    if (process.platform !== 'win32' && child.pid) {
      process.kill(-child.pid, signal);
    } else {
      child.kill(signal);
    }
  } catch (error) {
    if (error.code !== 'ESRCH') {
      console.error(`tapebasis: could not forward ${signal}: ${error.message}`);
    }
  }
}

/**
 * Start uvx, forward the client's arguments and environment, and mirror its status.
 * The launcher stays present while the child runs so signals reach its process group.
 */
function main() {
  const launch = executable();
  const child = spawn(launch.command, [...launch.args, ...process.argv.slice(2)], {
    stdio: 'inherit',
    env: process.env,
    windowsHide: true,
    detached: process.platform !== 'win32',
    shell: false,
  });
  let forwarded = null;
  for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(signal, () => {
      forwarded = signal;
      forwardSignal(child, signal);
    });
  }

  child.on('error', (error) => {
    if (error.code === 'ENOENT') {
           console.error([
        'tapebasis: uv is required but uvx was not found on PATH.',
        'Install uv: https://docs.astral.sh/uv/getting-started/installation/',
        'Then restart this MCP client, or set TAPEBASIS_UVX to the uvx executable.',
      ].join('\n'));
      process.exitCode = 127;
    } else {
      console.error(`tapebasis: could not start uvx: ${error.message}`);
      process.exitCode = 1;
    }
  });
  child.on('exit', (code, signal) => {
    if (forwarded && !process.platform.startsWith('win')) {
      // Preserve a normal shell signal status, including Bash's 130 for Ctrl-C.
      process.exitCode = 128 + (constants.signals[forwarded] || 1);
    } else if (signal) {
      process.exitCode = 128 + (constants.signals[signal] || 1);
    } else {
      process.exitCode = code === null ? 1 : code;
    }
  });
}

main();
