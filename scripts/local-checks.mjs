import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  readFileSync,
  readdirSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { join, resolve } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const directories = { python: ".venv", web: "web/node_modules" };
const inputs = {
  python: ["pyproject.toml", "uv.lock", ".python-version"],
  web: ["web/package.json", "web/package-lock.json"],
};

export function dependencyFingerprint(root, name, runtimeRoot = root) {
  const digest = createHash("sha256").update(
    `${process.platform}/${process.arch}/${process.version}`,
  );
  if (name === "python")
    digest.update(
      execFileSync(
        join(runtimeRoot, ".venv/bin/python"),
        [
          "-I",
          "-c",
          "import importlib.util, sys; print(sys.version); print(importlib.util.find_spec('quarry') is None)",
        ],
        {
          encoding: "utf8",
        },
      ),
    );
  for (const file of inputs[name])
    digest.update(file).update(readFileSync(join(root, file)));
  return digest.digest("hex");
}

function requireDependencies(source, target) {
  for (const [name, directory] of Object.entries(directories)) {
    const stamp = join(source, directory, ".quarry-dependencies");
    if (
      !existsSync(stamp) ||
      readFileSync(stamp, "utf8") !==
        dependencyFingerprint(target, name, source)
    ) {
      throw new Error(
        `${name} dependencies do not match the snapshot; run make deps, then retry.`,
      );
    }
  }
}

export function attachDependencies(source, target) {
  requireDependencies(source, target);
  for (const directory of Object.values(directories))
    symlinkSync(join(source, directory), join(target, directory), "dir");
}

export function offlineEnvironment(root) {
  const env = {
    ...process.env,
    UV_OFFLINE: "1",
    UV_PYTHON_DOWNLOADS: "never",
    VIRTUAL_ENV: join(root, ".venv"),
    PYTHONPATH: `${join(root, "scripts/test_python")}:${join(root, "src")}`,
    NODE_OPTIONS: `${process.env.NODE_OPTIONS ?? ""} --require=${JSON.stringify(join(root, "scripts/no-network.cjs"))}`,
  };
  for (const key of Object.keys(env)) {
    if (
      key.startsWith("GIT_") ||
      /^(UV_PYTHON|QUARRY_.*(API_KEY|MSSQL_DSN|LIVE_PROVIDERS)|ANTHROPIC_API_KEY|OPENAI_API_KEY)$/.test(
        key,
      )
    )
      delete env[key];
  }
  return env;
}

export function runChecks(root, suite, paths = []) {
  let python = join(root, ".venv/bin/python");
  const checkEnv = offlineEnvironment(root);
  const run = (command, args, cwd = root, env = checkEnv) => {
    console.log(`\n> ${command} ${args.join(" ")}`);
    execFileSync(command, args, { cwd, env, stdio: "inherit" });
  };
  const npm = (...args) => run("npm", args, join(root, "web"));
  if (suite === "deps") {
    // Setup is the only command that downloads dependencies or browser binaries.
    for (const directory of Object.values(directories)) {
      const stamp = join(root, directory, ".quarry-dependencies");
      if (existsSync(stamp)) writeFileSync(stamp, "");
    }
    const env = { ...process.env };
    env.UV_PROJECT_ENVIRONMENT = join(root, ".venv");
    env.VIRTUAL_ENV = env.UV_PROJECT_ENVIRONMENT;
    delete env.UV_PYTHON;
    delete env.UV_OFFLINE;
    delete env.UV_PYTHON_DOWNLOADS;
    run(
      "uv",
      ["sync", "--locked", "--no-install-project", "--reinstall"],
      root,
      env,
    );
    run("npm", ["ci", "--no-audit", "--no-fund"], join(root, "web"), env);
    run(
      python,
      [
        "-m",
        "playwright",
        "install",
        ...(process.platform === "linux" ? ["--with-deps"] : []),
        "chromium",
      ],
      root,
      env,
    );
    for (const [name, directory] of Object.entries(directories))
      writeFileSync(
        join(root, directory, ".quarry-dependencies"),
        dependencyFingerprint(root, name),
      );
    return;
  }
  if (!["smoke", "full", "coverage"].includes(suite))
    throw new Error(`Unknown suite: ${suite}`);
  requireDependencies(root, root);
  run(process.execPath, [
    "--test",
    "scripts/git-gate.test.mjs",
    "scripts/local-checks.test.mjs",
    ...(suite === "smoke" ? [] : ["scripts/snapshot-import.test.mjs"]),
  ]);
  if (suite === "smoke") {
    const pythonFiles = paths.filter((path) => path.endsWith(".py"));
    if (pythonFiles.length) {
      run(python, ["-m", "ruff", "check", ...pythonFiles]);
      run(python, ["-m", "ruff", "format", "--check", ...pythonFiles]);
    }
    const { transformSync } = createRequire(join(root, "web/package.json"))(
      "esbuild",
    );
    for (const path of paths) {
      if (/\.(ts|tsx)$/.test(path))
        transformSync(readFileSync(join(root, path), "utf8"), {
          loader: path.endsWith(".tsx") ? "tsx" : "ts",
          sourcefile: path,
        });
      if (/\.(mjs|cjs|js)$/.test(path))
        run(process.execPath, ["--check", path]);
    }
    run(python, [
      "-m",
      "pytest",
      "-n",
      "0",
      "-q",
      "tests/test_config.py",
      "tests/query/test_spec.py",
    ]);
    npm(
      "test",
      "--",
      "--project=node",
      "src/shared/base64.test.ts",
      "src/runtime/perspective/filters.test.ts",
      "src/runtime/perspective/toSpec.test.ts",
    );
    return;
  }
  // Isolated Python exports (-I) need the checked package, never a shared checkout install.
  checkEnv.UV_PROJECT_ENVIRONMENT = join(root, ".check-venv");
  checkEnv.VIRTUAL_ENV = checkEnv.UV_PROJECT_ENVIRONMENT;
  run("uv", ["sync", "--locked", "--offline", "--no-install-project"]);
  python = join(root, ".check-venv/bin/python");
  run(python, ["-m", "ruff", "check", "src", "tests", "scripts/test_python"]);
  run(python, [
    "-m",
    "ruff",
    "format",
    "--check",
    "src",
    "tests",
    "scripts/test_python",
  ]);
  run(python, ["-m", "mypy", "src", "tests", "scripts/test_python"]);
  const markdown = [
    "README.md",
    "AGENTS.md",
    ...["docs", "docs/context"].flatMap((directory) =>
      readdirSync(join(root, directory))
        .filter((file) => file.endsWith(".md"))
        .map((file) => `${directory}/${file}`),
    ),
  ];
  run(process.execPath, [
    "web/node_modules/prettier/bin/prettier.cjs",
    "--check",
    ...markdown,
    "scripts/*.mjs",
    "scripts/*.cjs",
  ]);
  npm("run", "check");
  npm("test");
  npm("run", "build");
  // Assert assets and Chromium before pytest can skip browser or transpile coverage.
  const requiredAssets = [
    "index.html",
    "runtime.html",
    "runtime-manifest.json",
    "transpile-check.mjs",
  ];
  for (const file of requiredAssets) {
    if (!readFileSync(join(root, "src/quarry/static", file)).length)
      throw new Error(`Empty built asset: ${file}`);
  }
  run(python, [
    "-c",
    "from pathlib import Path; from playwright.sync_api import sync_playwright;\nwith sync_playwright() as p:\n    assert Path(p.chromium.executable_path).is_file(), 'Chromium missing; run make deps'",
  ]);
  rmSync(join(root, "dist"), { recursive: true, force: true });
  run("uv", ["build", "--offline", "--no-build-isolation", "--python", python]);
  run(python, [
    "-c",
    `from pathlib import Path; from zipfile import ZipFile;\nwheel = next(Path('dist').glob('*.whl'))\nwith ZipFile(wheel) as z:\n    for name in ${JSON.stringify(requiredAssets)}:\n        assert z.read('quarry/static/' + name), name\n    assert any(n.startswith('quarry/static/assets/') for n in z.namelist())\nprint('Wheel includes UI, runtime manifest, TSX checker and bundled assets')`,
  ]);
  const wheel = readdirSync(join(root, "dist")).find((file) =>
    file.endsWith(".whl"),
  );
  run("uv", [
    "pip",
    "install",
    "--offline",
    "--no-deps",
    "--python",
    python,
    join(root, "dist", wheel),
  ]);
  const sitePackages = execFileSync(
    python,
    ["-c", "import site; print(site.getsitepackages()[0])"],
    { env: checkEnv, encoding: "utf8" },
  ).trim();
  copyFileSync(
    join(root, "scripts/test_python/sitecustomize.py"),
    join(sitePackages, "sitecustomize.py"),
  );
  run(python, [
    "-m",
    "pytest",
    "-q",
    "-rs",
    "--durations=10",
    ...(suite === "coverage"
      ? [
          "--cov=quarry",
          "--cov-branch",
          "--cov-report=term-missing",
          "--cov-report=xml:coverage.xml",
        ]
      : []),
  ]);
}

if (
  process.argv[1] &&
  realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  try {
    runChecks(
      resolve(fileURLToPath(new URL("..", import.meta.url))),
      process.argv[2] ?? "full",
      process.argv.slice(3),
    );
  } catch (error) {
    console.error(
      `Local checks failed: ${error.message}\nFor missing dependencies or cached packages, run make deps, then retry.`,
    );
    process.exitCode = 1;
  }
}
