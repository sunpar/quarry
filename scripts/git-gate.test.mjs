import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  chmodSync,
  copyFileSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { withSnapshot, gatePush, createPr } from "./git-gate.mjs";

function repository(t) {
  const root = mkdtempSync(join(tmpdir(), "quarry-gate-test-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const git = (...args) =>
    execFileSync("git", args, {
      cwd: root,
      encoding: "utf8",
      stdio: "pipe",
    }).trim();
  git("init", "-q", "-b", "feature");
  git("config", "user.email", "test@example.com");
  git("config", "user.name", "Test");
  git("config", "core.hooksPath", "/dev/null");
  writeFileSync(join(root, "value.txt"), "committed");
  git("add", ".");
  git("commit", "-qm", "Initial");
  return { root, git };
}

test("staged snapshot excludes unstaged fixes, untracked files, and staged deletions", async (t) => {
  const { root, git } = repository(t);
  writeFileSync(join(root, "value.txt"), "staged failure");
  git("add", ".");
  writeFileSync(join(root, "value.txt"), "unstaged fix");
  writeFileSync(join(root, "untracked.txt"), "untracked");
  let snapshot;
  await withSnapshot(root, { staged: true }, async (directory) => {
    snapshot = directory;
    assert.equal(
      readFileSync(join(directory, "value.txt"), "utf8"),
      "staged failure",
    );
    assert.throws(
      () => readFileSync(join(directory, "untracked.txt")),
      /ENOENT/,
    );
  });
  assert.throws(() => readFileSync(join(snapshot, "value.txt")), /ENOENT/);
  assert.equal(git("show", ":value.txt"), "staged failure");
  assert.equal(readFileSync(join(root, "value.txt"), "utf8"), "unstaged fix");
  git("rm", "-f", "--cached", "value.txt");
  await withSnapshot(root, { staged: true }, async (directory) => {
    assert.throws(() => readFileSync(join(directory, "value.txt")), /ENOENT/);
  });
});

test("committed snapshot tests the requested non-HEAD ref and cleans up after failure", async (t) => {
  const { root, git } = repository(t);
  const sha = git("rev-parse", "HEAD");
  writeFileSync(join(root, "value.txt"), "new tip");
  git("commit", "-qam", "Next");
  let snapshot;
  await assert.rejects(
    withSnapshot(root, { ref: sha }, async (directory) => {
      snapshot = directory;
      assert.equal(
        readFileSync(join(directory, "value.txt"), "utf8"),
        "committed",
      );
      throw new Error("test failed");
    }),
    /test failed/,
  );
  assert.throws(() => readFileSync(join(snapshot, "value.txt")), /ENOENT/);
});

test("push checks each distinct qualifying tip once, ignores deletions, and does not test private branches", async (t) => {
  const { root, git } = repository(t);
  const sha = git("rev-parse", "HEAD");
  const checked = [];
  const run = (command, args) => {
    assert.equal(command, "gh");
    if (args[0] === "repo")
      return JSON.stringify({
        nameWithOwner: "owner/repo",
        isFork: true,
        parent: { owner: { login: "upstream" }, name: "repo" },
      });
    assert.ok(
      ["owner/repo", "upstream/repo"].includes(
        args[args.indexOf("--repo") + 1],
      ),
    );
    return JSON.stringify(
      args.includes("feature")
        ? [
            {
              headRepository: { name: "repo" },
              headRepositoryOwner: { login: "owner" },
            },
          ]
        : [],
    );
  };
  const zero = "0".repeat(40);
  const input = `refs/heads/feature ${sha} refs/heads/feature ${zero}\nrefs/heads/main ${sha} refs/heads/main ${zero}\nrefs/heads/private ${sha} refs/heads/private ${zero}\n(delete) ${zero} refs/heads/old ${sha}\n`;
  await gatePush(
    root,
    "git@github.com:owner/repo.git",
    input,
    run,
    async (ref) => checked.push(ref),
  );
  assert.deepEqual(checked, [sha]);
});

test("PR lookup and test failures abort pushes instead of being treated as no PR", async (t) => {
  const { root, git } = repository(t);
  const input = `refs/heads/feature ${git("rev-parse", "HEAD")} refs/heads/feature ${"0".repeat(40)}`;
  await assert.rejects(
    gatePush(root, "origin", input, () => {
      throw new Error("GitHub unavailable");
    }),
    /GitHub unavailable/,
  );
  const run = (_command, args) =>
    JSON.stringify(
      args[0] === "repo"
        ? { nameWithOwner: "owner/repo", isFork: false }
        : [
            {
              headRepository: { name: "repo" },
              headRepositoryOwner: { login: "owner" },
            },
          ],
    );
  await assert.rejects(
    gatePush(root, "origin", input, run, async () => {
      throw new Error("suite failed");
    }),
    /suite failed/,
  );
});

test("failed PR checks never push or create a PR", async (t) => {
  const { root, git } = repository(t);
  const effects = [];
  const run = (command, args) => {
    if (command === "git") return git(...args);
    effects.push([command, ...args]);
    return JSON.stringify({ nameWithOwner: "owner/repo", isFork: false });
  };
  await assert.rejects(
    createPr(root, [], run, async () => {
      throw new Error("suite failed");
    }),
    /suite failed/,
  );
  assert.deepEqual(effects, []);
});

test("PR wrapper rejects destination overrides and a changing HEAD", async (t) => {
  const { root, git } = repository(t);
  await assert.rejects(
    createPr(root, ["--head=unchecked"]),
    /head|destination/i,
  );
  await assert.rejects(
    createPr(root, ["-dHunchecked"]),
    /flag|head|destination/i,
  );
  git("remote", "add", "origin", "git@github.com:owner/repo.git");
  await assert.rejects(
    createPr(root, [], undefined, async () => {
      writeFileSync(join(root, "value.txt"), "changed during checks");
      git("commit", "-qam", "Changed");
    }),
    /changed.*checks/i,
  );
});

test("PR creation pushes the checked SHA and configures subsequent default pushes", async (t) => {
  const { root, git } = repository(t);
  const remote = join(root, "remote.git");
  git("init", "--bare", "-q", remote);
  git("remote", "add", "origin", remote);
  const sha = git("rev-parse", "HEAD");
  writeFileSync(join(root, "value.txt"), "unstaged change");
  const run = (command, args, options = {}) => {
    if (command === "git") return git(...args);
    if (args[0] === "repo")
      return JSON.stringify({
        nameWithOwner: "organization/repo",
        isFork: true,
        parent: { owner: { login: "upstream" }, name: "repo" },
      });
    assert.equal(
      git("--git-dir", remote, "rev-parse", "refs/heads/feature"),
      sha,
    );
    assert.equal(args[args.indexOf("--repo") + 1], "upstream/repo");
    assert.equal(args[args.indexOf("--head") + 1], "organization:feature");
  };
  await createPr(root, ["--title", "Test"], run, async (ref) => {
    await withSnapshot(root, { ref }, async (directory) => {
      assert.equal(
        readFileSync(join(directory, "value.txt"), "utf8"),
        "committed",
      );
    });
  });
  assert.equal(git("config", "branch.feature.remote"), "origin");
  assert.equal(git("config", "branch.feature.merge"), "refs/heads/feature");
  assert.equal(
    readFileSync(join(root, "value.txt"), "utf8"),
    "unstaged change",
  );
});

test("real pre-push hook stops an open-PR push when local dependencies are missing", (t) => {
  const { root, git } = repository(t);
  const remote = join(root, "remote.git");
  git("init", "--bare", "-q", remote);
  git("remote", "add", "origin", remote);
  git("push", "-q", "origin", "feature");
  const before = git("rev-parse", "HEAD");
  mkdirSync(join(root, ".githooks"));
  mkdirSync(join(root, "scripts"));
  mkdirSync(join(root, "bin"));
  for (const file of ["git-gate.mjs", "local-checks.mjs"])
    copyFileSync(new URL(file, import.meta.url), join(root, "scripts", file));
  copyFileSync(
    new URL("../.githooks/pre-push", import.meta.url),
    join(root, ".githooks/pre-push"),
  );
  chmodSync(join(root, ".githooks/pre-push"), 0o755);
  const gh = join(root, "bin/gh");
  writeFileSync(
    gh,
    `#!/usr/bin/env node\nconsole.log(JSON.stringify(process.argv[2] === 'repo'
    ? { nameWithOwner: 'owner/repo', isFork: false }
    : [{ headRepository: { name: 'repo' }, headRepositoryOwner: { login: 'owner' } }]))`,
  );
  chmodSync(gh, 0o755);
  writeFileSync(join(root, "value.txt"), "next commit");
  git("commit", "-qam", "Next");
  git("config", "core.hooksPath", ".githooks");
  assert.throws(
    () =>
      execFileSync("git", ["push", "origin", "feature"], {
        cwd: root,
        encoding: "utf8",
        stdio: "pipe",
        env: {
          ...process.env,
          PATH: `${join(root, "bin")}:${process.env.PATH}`,
        },
      }),
    /dependencies.*make deps/,
  );
  assert.equal(
    git("--git-dir", remote, "rev-parse", "refs/heads/feature"),
    before,
  );
});

test("CLI entrypoints invoked through a path alias execute and fail on missing dependencies", (t) => {
  const { root } = repository(t);
  mkdirSync(join(root, "scripts"));
  for (const file of ["git-gate.mjs", "local-checks.mjs"])
    copyFileSync(new URL(file, import.meta.url), join(root, "scripts", file));
  symlinkSync(join(root, "scripts"), join(root, "alias-scripts"), "dir");
  for (const [file, operation] of [
    ["local-checks.mjs", "smoke"],
    ["git-gate.mjs", "check"],
  ]) {
    assert.throws(
      () =>
        execFileSync(
          process.execPath,
          [join(root, "alias-scripts", file), operation],
          {
            cwd: root,
            encoding: "utf8",
            stdio: "pipe",
          },
        ),
      /dependencies.*make deps/,
    );
  }
});

test("PR CLI dispatch reaches gh help without validation or mutation", (t) => {
  const { root } = repository(t);
  const output = execFileSync(
    process.execPath,
    [new URL("git-gate.mjs", import.meta.url).pathname, "pr", "--help"],
    { cwd: root, encoding: "utf8", stdio: "pipe" },
  );
  assert.match(output, /Create a pull request/);
});

test("unsupported dry-run cannot push a real branch", async (t) => {
  const { root } = repository(t);
  await assert.rejects(createPr(root, ["--dry-run"]), /Unsupported PR flag/);
});

test("renamed push destinations use outgoing SHA and upstream fork PRs", async (t) => {
  const { root, git } = repository(t);
  const sha = git("rev-parse", "HEAD");
  const calls = [];
  const checked = [];
  const run = (command, args) => {
    calls.push([command, ...args]);
    if (args[0] === "repo") {
      assert.equal(args[2], "git@github.com:owner/fork.git");
      return JSON.stringify({
        nameWithOwner: "owner/fork",
        isFork: true,
        parent: { owner: { login: "upstream" }, name: "repo" },
      });
    }
    assert.equal(args[args.indexOf("--head") + 1], "destination");
    return JSON.stringify(
      args.includes("upstream/repo")
        ? [
            {
              headRepository: { name: "fork" },
              headRepositoryOwner: { login: "owner" },
            },
          ]
        : [],
    );
  };
  await gatePush(
    root,
    "git@github.com:owner/fork.git",
    `refs/heads/local ${sha} refs/heads/destination ${"f".repeat(40)}\nrefs/tags/v1 ${sha} refs/tags/v1 ${"0".repeat(40)}`,
    run,
    async (ref) => checked.push(ref),
  );
  assert.deepEqual(checked, [sha]);
  assert.equal(calls.filter(([, operation]) => operation === "pr").length, 2);
});
