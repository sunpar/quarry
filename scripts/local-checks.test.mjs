import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import {
  attachDependencies,
  dependencyFingerprint,
  offlineEnvironment,
} from "./local-checks.mjs";

const source = import.meta.dirname + "/..";
const python = join(source, ".venv/bin/python");

test("dependency inputs and runtime determine whether snapshots can reuse installed tools", (t) => {
  const target = mkdtempSync(join(tmpdir(), "quarry-deps-"));
  t.after(() => rmSync(target, { recursive: true, force: true }));
  mkdirSync(join(target, "web"));
  for (const path of [
    "uv.lock",
    "pyproject.toml",
    ".python-version",
    "web/package.json",
    "web/package-lock.json",
  ])
    cpSync(join(source, path), join(target, path));
  for (const name of ["python", "web"]) {
    assert.equal(
      dependencyFingerprint(source, name),
      dependencyFingerprint(target, name, source),
    );
  }
  writeFileSync(join(target, ".python-version"), "3.12\n");
  assert.throws(
    () => attachDependencies(source, target),
    /dependencies.*make deps/,
  );
  cpSync(join(source, ".python-version"), join(target, ".python-version"));
  writeFileSync(join(target, "web/package.json"), "{}");
  assert.throws(
    () => attachDependencies(source, target),
    /dependencies.*make deps/,
  );
});

test("offline processes strip live credentials and reject remote Python and Node sockets", () => {
  const env = offlineEnvironment(source);
  assert.equal(env.QUARRY_ANTHROPIC_API_KEY, undefined);
  assert.equal(env.QUARRY_OPENAI_API_KEY, undefined);
  for (const method of ["connect", "connect_ex"]) {
    assert.throws(
      () =>
        execFileSync(
          python,
          [
            "-c",
            `import socket; socket.socket().${method}(('203.0.113.1', 443))`,
          ],
          { env, stdio: "pipe" },
        ),
      /External network disabled/,
    );
  }
  for (const host of ["example.com", "203.0.113.1", "2001:db8::1"]) {
    assert.throws(
      () =>
        execFileSync(
          process.execPath,
          ["-e", `require('node:net').connect(443, ${JSON.stringify(host)})`],
          { env, stdio: "pipe" },
        ),
      /External network disabled/,
    );
  }
  execFileSync(
    python,
    [
      "-c",
      `import subprocess, sys\nresult = subprocess.run([sys.executable, '-c', "import socket; socket.socket().connect(('203.0.113.1', 443))"], capture_output=True, text=True)\nassert result.returncode != 0 and 'External network disabled' in result.stderr`,
    ],
    { env },
  );
});

test("offline Node and Python retain IPv4 and IPv6 loopback", async () => {
  for (const host of ["127.0.0.1", "::1"]) {
    const code = `const net = require('node:net'); const server = net.createServer(socket => socket.end('local')); server.listen(0, ${JSON.stringify(host)}, () => { const client = net.connect(server.address().port, ${JSON.stringify(host)}); client.on('data', chunk => { if (chunk.toString() !== 'local') process.exitCode = 1; }); client.on('end', () => server.close()); });`;
    await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, ["-e", code], {
        env: offlineEnvironment(source),
        stdio: "pipe",
      });
      child.on("error", reject);
      child.on("exit", (status) =>
        status === 0
          ? resolve()
          : reject(new Error(`loopback failed: ${status}`)),
      );
    });
    execFileSync(
      python,
      [
        "-c",
        `import socket\nfamily = socket.AF_INET6 if ':' in ${JSON.stringify(host)} else socket.AF_INET\nwith socket.socket(family) as server, socket.socket(family) as client:\n    server.bind((${JSON.stringify(host)}, 0))\n    server.listen()\n    client.connect(server.getsockname())\n    connection, _ = server.accept()\n    connection.close()`,
      ],
      { env: offlineEnvironment(source) },
    );
  }
});

test("installing Quarry into shared tools invalidates their snapshot fingerprint", (t) => {
  const target = mkdtempSync(join(tmpdir(), "quarry-tool-install-"));
  t.after(() => rmSync(target, { recursive: true, force: true }));
  for (const file of ["uv.lock", "pyproject.toml", ".python-version"])
    cpSync(join(source, file), join(target, file));
  execFileSync(
    "uv",
    ["venv", "--offline", "--python", python, join(target, ".venv")],
    { stdio: "pipe" },
  );
  const runtime = join(target, ".venv/bin/python");
  const before = dependencyFingerprint(target, "python");
  const site = execFileSync(
    runtime,
    ["-I", "-c", "import site; print(site.getsitepackages()[0])"],
    { encoding: "utf8" },
  ).trim();
  writeFileSync(join(site, "quarry.py"), 'SNAPSHOT = "installed checkout"\n');
  assert.notEqual(dependencyFingerprint(target, "python"), before);
});
