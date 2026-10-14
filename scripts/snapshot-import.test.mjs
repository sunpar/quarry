import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { cpSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { attachDependencies, offlineEnvironment } from "./local-checks.mjs";
const source = import.meta.dirname + "/..";
const python = join(source, ".venv/bin/python");

test("Python parent, xdist workers and real kernel import only the snapshot", (t) => {
  const target = mkdtempSync(join(tmpdir(), "quarry-import-"));
  t.after(() => rmSync(target, { recursive: true, force: true }));
  for (const path of [
    "src",
    "scripts",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    "web/package.json",
    "web/package-lock.json",
  ])
    cpSync(join(source, path), join(target, path), {
      recursive: true,
      filter: (path) => !path.includes("/src/quarry/static"),
    });
  attachDependencies(source, target);
  writeFileSync(
    join(target, "src/quarry/__init__.py"),
    "SNAPSHOT = 'staged'\n",
  );
  const env = offlineEnvironment(target);
  const check = `import quarry; from pathlib import Path; assert quarry.SNAPSHOT == 'staged'; assert Path(quarry.__file__).resolve().is_relative_to(Path(${JSON.stringify(target)}).resolve())`;
  execFileSync(python, ["-c", check], { cwd: target, env });
  writeFileSync(
    join(target, "test_snapshot.py"),
    `def test_snapshot():\n    ${check}\n`,
  );
  execFileSync(python, ["-m", "pytest", "-q", "-n", "2", "test_snapshot.py"], {
    cwd: target,
    env,
    stdio: "pipe",
  });
  execFileSync(
    python,
    [
      "-c",
      `from quarry.kernel.client import KernelClient\nkernel = KernelClient.spawn(__import__('pathlib').Path(${JSON.stringify(target)}))\ntry:\n    result = kernel.execute(${JSON.stringify(check)})\n    assert result.status == 'ok', result\nfinally:\n    kernel.close()`,
    ],
    { cwd: target, env },
  );
  rmSync(join(target, "src/quarry"), { recursive: true });
  assert.throws(
    () =>
      execFileSync(python, ["-c", "import quarry"], {
        cwd: target,
        env,
        stdio: "pipe",
      }),
    /No module named 'quarry'/,
  );
});
