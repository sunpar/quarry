import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { attachDependencies } from "./local-checks.mjs";

function commandRunner(root) {
  const env = { ...process.env };
  for (const key of ["GIT_DIR", "GIT_WORK_TREE", "GIT_PREFIX"]) delete env[key];
  return (command, args, options = {}) =>
    execFileSync(command, args, {
      cwd: root,
      env,
      encoding: "utf8",
      maxBuffer: 256 * 1024 * 1024,
      ...options,
    })?.trim();
}

export async function withSnapshot(root, { staged = false, ref }, action) {
  const directory = mkdtempSync(join(tmpdir(), "quarry-check-"));
  const run = commandRunner(root);
  try {
    if (staged) {
      run("git", ["checkout-index", "--all", `--prefix=${directory}/`]);
    } else {
      const archive = execFileSync("git", ["-C", root, "archive", ref], {
        maxBuffer: 256 * 1024 * 1024,
      });
      execFileSync("tar", ["-x", "-C", directory], { input: archive });
    }
    return await action(directory);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

async function checkSnapshot(root, selection, suite, paths = []) {
  await withSnapshot(root, selection, async (snapshot) => {
    attachDependencies(root, snapshot);
    const env = { ...process.env, PYTHONPATH: join(snapshot, "src") };
    for (const key of Object.keys(env))
      if (key.startsWith("GIT_")) delete env[key];
    execFileSync(
      process.execPath,
      [join(snapshot, "scripts/local-checks.mjs"), suite, ...paths],
      {
        cwd: snapshot,
        env,
        stdio: "inherit",
      },
    );
  });
}

export async function gatePush(
  root,
  remote,
  input,
  run = commandRunner(root),
  check = (ref) => checkSnapshot(root, { ref }, "full"),
) {
  const updates = input
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => line.split(/\s+/))
    .filter(
      ([, sha, destination]) =>
        !/^0+$/.test(sha) && destination.startsWith("refs/heads/"),
    );
  if (!updates.length) return;
  const destination = JSON.parse(
    run("gh", [
      "repo",
      "view",
      remote,
      "--json",
      "nameWithOwner,isFork,parent",
    ]),
  );
  const tips = new Set();
  for (const [, sha, ref] of updates) {
    const branch = ref.slice("refs/heads/".length);
    const repositories = [
      destination.nameWithOwner,
      ...(destination.isFork
        ? [`${destination.parent.owner.login}/${destination.parent.name}`]
        : []),
    ];
    const prs = repositories.flatMap((repository) =>
      JSON.parse(
        run("gh", [
          "pr",
          "list",
          "--repo",
          repository,
          "--state",
          "open",
          "--head",
          branch,
          "--json",
          "headRepository,headRepositoryOwner",
        ]),
      ),
    );
    const open = prs.some(
      (pr) =>
        `${pr.headRepositoryOwner.login}/${pr.headRepository.name}`.toLowerCase() ===
        destination.nameWithOwner.toLowerCase(),
    );
    // Direct main pushes receive the same checks as PR updates.
    if (open || branch === "main") tips.add(sha);
  }
  for (const sha of tips) {
    console.log(`Checking commit ${sha.slice(0, 12)} before push…`);
    await check(sha);
  }
}

export async function createPr(
  root,
  args,
  run = commandRunner(root),
  check = (ref) => checkSnapshot(root, { ref }, "full"),
) {
  const values = new Set([
    "--title",
    "-t",
    "--body",
    "-b",
    "--body-file",
    "-F",
    "--base",
    "-B",
    "--reviewer",
    "-r",
    "--label",
    "-l",
    "--milestone",
    "-m",
    "--project",
    "-p",
    "--template",
    "-T",
    "--attach",
    "--recover",
  ]);
  const switches = new Set([
    "--draft",
    "-d",
    "--fill",
    "-f",
    "--fill-first",
    "--fill-verbose",
    "--no-maintainer-edit",
    "--editor",
    "-e",
    "--web",
    "-w",
  ]);
  if (args.length === 1 && args[0] === "--help")
    return run("gh", ["pr", "create", "--help"], { stdio: "inherit" });
  for (let i = 0; i < args.length; i++) {
    const flag = args[i].split("=")[0];
    if (values.has(flag)) {
      if (!args[i].includes("=") && args[++i] === undefined)
        throw new Error(`Missing value for PR flag ${flag}`);
    } else if (!switches.has(args[i])) {
      throw new Error(
        `Unsupported PR flag ${args[i]}; head/repo overrides and grouped short flags are not supported.`,
      );
    }
  }
  const branch = run("git", ["symbolic-ref", "--short", "HEAD"]);
  const sha = run("git", ["rev-parse", "HEAD"]);
  await check(sha);
  if (
    sha !== run("git", ["rev-parse", "HEAD"]) ||
    branch !== run("git", ["symbolic-ref", "--short", "HEAD"])
  ) {
    throw new Error("HEAD changed during checks; run make pr again.");
  }
  const remote = run("git", ["remote", "get-url", "--push", "origin"]);
  const repo = JSON.parse(
    run("gh", [
      "repo",
      "view",
      remote,
      "--json",
      "nameWithOwner,isFork,parent",
    ]),
  );
  run("git", ["push", "origin", `${sha}:refs/heads/${branch}`], {
    stdio: "inherit",
  });
  // A SHA push preserves verification fidelity; branch tracking is a separate operation.
  run("git", ["branch", `--set-upstream-to=origin/${branch}`, branch], {
    stdio: "inherit",
  });
  run(
    "gh",
    [
      "pr",
      "create",
      "--repo",
      repo.isFork
        ? `${repo.parent.owner.login}/${repo.parent.name}`
        : repo.nameWithOwner,
      "--head",
      repo.isFork ? `${repo.nameWithOwner.split("/")[0]}:${branch}` : branch,
      "--assignee",
      "@me",
      ...args,
    ],
    { stdio: "inherit" },
  );
}

if (
  process.argv[1] &&
  realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  try {
    const root = execFileSync("git", ["rev-parse", "--show-toplevel"], {
      encoding: "utf8",
    }).trim();
    const [operation, ...args] = process.argv.slice(2);
    if (operation === "commit") {
      const paths = execFileSync(
        "git",
        ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"],
        { encoding: "utf8" },
      )
        .split("\0")
        .filter(Boolean);
      await checkSnapshot(root, { staged: true }, "smoke", paths);
    } else if (operation === "push") {
      await gatePush(root, args[1] ?? args[0], readFileSync(0, "utf8"));
    } else if (operation === "pr") {
      await createPr(root, args[0] === "--" ? args.slice(1) : args);
    } else if (operation === "check") {
      await checkSnapshot(root, { ref: args[0] ?? "HEAD" }, "full");
    } else {
      throw new Error(
        "Usage: git-gate.mjs commit | push <remote> <url> | pr [gh options] | check [commit]",
      );
    }
  } catch (error) {
    console.error(
      `Local checks failed; operation stopped. Run make deps for missing tools; run gh auth status for PR lookup failures. ${error.message}`,
    );
    process.exitCode = 1;
  }
}
