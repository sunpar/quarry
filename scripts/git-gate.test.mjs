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
import { withSnapshot, gatePush, createPr, installHooks } from "./git-gate.mjs";

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
  const mainSha = "1".repeat(40);
  const privateSha = "2".repeat(40);
  const checked = [];
  const run = (command, args) => {
    assert.equal(command, "gh");
    if (args[0] === "repo")
      return JSON.stringify({
        nameWithOwner: "owner/repo",
        isFork: true,
        parent: { owner: { login: "middle" }, name: "repo" },
      });
    if (args[1] === "repos/owner/repo")
      return JSON.stringify({
        parent: { full_name: "middle/repo" },
        source: { full_name: "upstream/repo" },
      });
    assert.ok(
      [
        "repos/owner/repo/pulls",
        "repos/middle/repo/pulls",
        "repos/upstream/repo/pulls",
      ].includes(args[1]),
    );
    return JSON.stringify([
      args[1] === "repos/upstream/repo/pulls" &&
      (args.includes("head=owner:feature") || args.includes("head=owner:alias"))
        ? [
            {
              head: { repo: { full_name: "owner/repo" } },
            },
          ]
        : [],
    ]);
  };
  const zero = "0".repeat(40);
  const input = `refs/heads/feature ${sha} refs/heads/feature ${zero}\nrefs/heads/feature ${sha} refs/heads/alias ${zero}\nrefs/heads/main ${mainSha} refs/heads/main ${zero}\nrefs/heads/private ${privateSha} refs/heads/private ${zero}\n(delete) ${zero} refs/heads/old ${sha}\n`;
  await gatePush(
    root,
    "git@github.com:owner/repo.git",
    input,
    run,
    async (ref) => checked.push(ref),
  );
  assert.deepEqual(checked, [sha, mainSha]);
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
        : [[{ head: { repo: { full_name: "owner/repo" } } }]],
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
  git("remote", "add", "origin", "git@github.com:owner/repo.git");
  const effects = [];
  const run = (command, args) => {
    if (command === "git") return git(...args);
    effects.push([command, ...args]);
    return JSON.stringify({
      nameWithOwner: "owner/repo",
      isFork: false,
      defaultBranchRef: { name: "main" },
    });
  };
  await assert.rejects(
    createPr(root, ["--title", "Test"], run, async () => {
      throw new Error("suite failed");
    }),
    /suite failed/,
  );
  assert.ok(effects.every(([, operation]) => operation === "repo"));
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
    createPr(
      root,
      ["--title", "Test", "--base", "main"],
      (command, args) =>
        command === "git"
          ? git(...args)
          : JSON.stringify({
              nameWithOwner: "owner/repo",
              isFork: false,
              defaultBranchRef: { name: "main" },
            }),
      async () => {
        writeFileSync(join(root, "value.txt"), "changed during checks");
        git("commit", "-qam", "Changed");
      },
    ),
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
        defaultBranchRef: { name: "main" },
      });
    assert.equal(
      git("--git-dir", remote, "rev-parse", "refs/heads/feature"),
      sha,
    );
    if (args[0] === "api") {
      assert.equal(args[1], "repos/upstream/repo/pulls");
      assert.equal(JSON.parse(options.input).head, "organization:feature");
      return JSON.stringify({
        html_url: "https://github.com/upstream/repo/pull/1",
      });
    }
    assert.deepEqual(args, [
      "pr",
      "edit",
      "https://github.com/upstream/repo/pull/1",
      "--add-assignee",
      "@me",
    ]);
  };
  await createPr(
    root,
    ["--title", "Test", "--base", "main"],
    run,
    async (ref) => {
      await withSnapshot(root, { ref }, async (directory) => {
        assert.equal(
          readFileSync(join(directory, "value.txt"), "utf8"),
          "committed",
        );
      });
    },
  );
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
  mkdirSync(join(root, "scripts"));
  mkdirSync(join(root, "bin"));
  for (const file of ["git-gate.mjs", "local-checks.mjs"])
    copyFileSync(new URL(file, import.meta.url), join(root, "scripts", file));
  const gh = join(root, "bin/gh");
  writeFileSync(
    gh,
    `#!/usr/bin/env node\nconsole.log(JSON.stringify(process.argv[2] === 'repo'
    ? { nameWithOwner: 'owner/repo', isFork: false }
    : [[{ head: { repo: { full_name: 'owner/repo' } } }]]))`,
  );
  chmodSync(gh, 0o755);
  writeFileSync(join(root, "value.txt"), "next commit");
  git("add", "value.txt", "scripts");
  git("commit", "-qm", "Next");
  installHooks(root);
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

test("PR CLI dispatch shows supported options without validation or mutation", (t) => {
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
    if (args[1] === "repos/owner/fork")
      return JSON.stringify({
        parent: { full_name: "upstream/repo" },
        source: { full_name: "upstream/repo" },
      });
    assert.ok(args.includes("head=owner:destination"));
    return JSON.stringify(
      args[1] === "repos/upstream/repo/pulls"
        ? [
            {
              head: { repo: { full_name: "owner/fork" } },
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
  assert.equal(calls.filter(([, operation]) => operation === "api").length, 3);
});

test("open PR beyond the first page still verifies the outgoing commit", async (t) => {
  const { root, git } = repository(t);
  const sha = git("rev-parse", "HEAD");
  const checked = [];
  const run = (_command, args) => {
    if (args[0] === "repo")
      return JSON.stringify({ nameWithOwner: "owner/repo", isFork: false });
    assert.equal(args[0], "api");
    assert.ok(
      args.includes("--paginate") &&
        args.includes("--slurp") &&
        args.includes("head=owner:feature"),
    );
    return JSON.stringify([
      Array.from({ length: 30 }, (_, i) => ({
        head: { repo: { full_name: `owner/other-${i}` } },
      })),
      [{ head: { repo: { full_name: "owner/repo" } } }],
    ]);
  };
  await gatePush(
    root,
    "origin",
    `refs/heads/feature ${sha} refs/heads/feature ${"0".repeat(40)}`,
    run,
    async (ref) => checked.push(ref),
  );
  assert.deepEqual(checked, [sha]);
});

test("same-repository base and head are rejected before checking or pushing", async (t) => {
  for (const args of [[], ["--base=main"], ["-B", "main"]]) {
    const { root, git } = repository(t);
    git("branch", "-m", "main");
    git("remote", "add", "origin", "git@github.com:owner/repo.git");
    const effects = [];
    const run = (command, values) => {
      if (command === "git") {
        if (values[0] === "push") effects.push("push");
        return git(...values);
      }
      if (values[0] === "repo")
        return JSON.stringify({
          nameWithOwner: "owner/repo",
          isFork: false,
          defaultBranchRef: { name: "main" },
        });
      effects.push("create");
      return JSON.stringify({
        html_url: "https://github.com/owner/repo/pull/1",
      });
    };
    await assert.rejects(
      createPr(root, ["--title", "Change", ...args], run, async () =>
        effects.push("check"),
      ),
      /same.*branch|base.*head|head.*base/i,
    );
    assert.deepEqual(effects, []);
  }
});

test("organization fork PR uses the explicit head repository through the API", async (t) => {
  const { root, git } = repository(t);
  git("branch", "-m", "main");
  const remote = join(root, "remote.git");
  git("init", "--bare", "-q", remote);
  git("remote", "add", "origin", remote);
  const sha = git("rev-parse", "HEAD");
  const bodyFile = join(root, "body.txt");
  writeFileSync(bodyFile, "Multiline\nbody\n");
  const run = (command, args, options = {}) => {
    if (command === "git") return git(...args);
    if (args[0] === "repo")
      return JSON.stringify({
        nameWithOwner: "organization/fork",
        isFork: true,
        parent: { owner: { login: "organization" }, name: "base" },
        defaultBranchRef: { name: "main" },
      });
    if (args[0] === "api") {
      assert.equal(args[1], "repos/organization/base/pulls");
      assert.equal(
        git("--git-dir", remote, "rev-parse", "refs/heads/main"),
        sha,
      );
      assert.deepEqual(JSON.parse(options.input), {
        title: "Change",
        body: "Multiline\nbody\n",
        base: "main",
        head: "organization:main",
        head_repo: "fork",
        draft: true,
        maintainer_can_modify: true,
      });
      return JSON.stringify({
        html_url: "https://github.com/organization/base/pull/1",
      });
    }
    assert.deepEqual(args, [
      "pr",
      "edit",
      "https://github.com/organization/base/pull/1",
      "--add-assignee",
      "@me",
    ]);
  };
  await createPr(
    root,
    ["--title", "Change", "--body-file", bodyFile, "--base", "main", "--draft"],
    run,
    async (ref) => assert.equal(ref, sha),
  );
});

test("configured merge base is rejected before publishing the same branch", async (t) => {
  const { root, git } = repository(t);
  git("branch", "-m", "release");
  git("remote", "add", "origin", "git@github.com:owner/repo.git");
  git("config", "branch.release.gh-merge-base", "release");
  const run = (command, args) =>
    command === "git"
      ? git(...args)
      : JSON.stringify({
          nameWithOwner: "owner/repo",
          isFork: false,
          defaultBranchRef: { name: "main" },
        });
  await assert.rejects(
    createPr(root, ["--title", "Change"], run, async () =>
      assert.fail("must reject before verification"),
    ),
    /base and head are the same branch/,
  );
});

test("a narrow fetch refspec does not prevent verified PR creation", async (t) => {
  const { root, git } = repository(t);
  const remote = join(root, "remote.git");
  git("init", "--bare", "-q", remote);
  git("remote", "add", "origin", remote);
  git(
    "config",
    "remote.origin.fetch",
    "+refs/heads/main:refs/remotes/origin/main",
  );
  const sha = git("rev-parse", "HEAD");
  let created = false;
  const run = (command, args) => {
    if (command === "git") return git(...args);
    if (args[0] === "repo")
      return JSON.stringify({
        nameWithOwner: "owner/repo",
        isFork: false,
        defaultBranchRef: { name: "main" },
      });
    if (args[0] === "api") {
      created = true;
      return JSON.stringify({
        html_url: "https://github.com/owner/repo/pull/1",
      });
    }
  };
  await createPr(root, ["--title", "Change"], run, async (ref) =>
    assert.equal(ref, sha),
  );
  assert.ok(created);
  assert.throws(() =>
    git("rev-parse", "--verify", "refs/remotes/origin/feature"),
  );
  assert.equal(git("config", "branch.feature.remote"), "origin");
  assert.equal(git("config", "branch.feature.merge"), "refs/heads/feature");
});

test("installed bootstrap remains active on branches without tracked gate files", (t) => {
  const { root, git } = repository(t);
  const directory = installHooks(root);
  assert.equal(git("config", "--worktree", "core.hooksPath"), directory);
  assert.equal(
    readFileSync(join(directory, "pre-commit"), "utf8").includes(
      "git-gate.mjs",
    ),
    true,
  );
  // No tracked scripts or hook templates exist in this old commit.
  assert.throws(
    () =>
      execFileSync(
        "git",
        ["commit", "--allow-empty", "-m", "Old branch commit"],
        { cwd: root, encoding: "utf8", stdio: "pipe" },
      ),
    /Local checks failed/,
  );
  assert.equal(git("log", "--format=%s", "-1"), "Initial");
});

test("required assignment happens after a verified PR is created", async (t) => {
  const { root, git } = repository(t);
  const remote = join(root, "remote.git");
  git("init", "--bare", "-q", remote);
  git("remote", "add", "origin", remote);
  let created = false,
    checked = false;
  const run = (command, args) => {
    if (command === "git") return git(...args);
    if (args[0] === "repo")
      return JSON.stringify({
        nameWithOwner: "owner/repo",
        isFork: false,
        defaultBranchRef: { name: "main" },
      });
    if (args[0] === "api") {
      assert.ok(checked);
      created = true;
      return JSON.stringify({
        html_url: "https://github.com/owner/repo/pull/1",
      });
    }
    throw new Error("HTTP 403 assignment permission denied");
  };
  await assert.rejects(
    createPr(root, ["--title", "Change"], run, async () => {
      checked = true;
    }),
    /403 assignment/,
  );
  assert.ok(created);
});
