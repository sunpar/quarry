import { execFileSync } from "node:child_process";
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
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

export function installHooks(root, run = commandRunner(root)) {
  const directory = resolve(
    root,
    run("git", ["rev-parse", "--git-path", "local-gates"]),
  );
  mkdirSync(directory, { recursive: true });
  for (const file of ["git-gate.mjs", "local-checks.mjs"])
    writeFileSync(
      join(directory, file),
      readFileSync(new URL(file, import.meta.url)),
    );
  for (const [hook, operation] of [
    ["pre-commit", "commit"],
    ["pre-push", "push"],
  ]) {
    const path = join(directory, hook);
    writeFileSync(
      path,
      `#!/bin/sh\nset -eu\nexec node "$(dirname "$0")/git-gate.mjs" ${operation} "$@"\n`,
    );
    chmodSync(path, 0o755);
  }
  run("git", ["config", "extensions.worktreeConfig", "true"]);
  run("git", ["config", "--worktree", "core.hooksPath", directory]);
  console.log(
    `Installed local gates in ${directory}; rerun make hooks after gate updates.`,
  );
  return directory;
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
          "api",
          `repos/${repository}/pulls`,
          "--method",
          "GET",
          "--paginate",
          "--slurp",
          "-f",
          "state=open",
          "-f",
          `head=${destination.nameWithOwner.split("/")[0]}:${branch}`,
          "-f",
          "per_page=100",
        ]),
      ).flat(),
    );
    const open = prs.some(
      (pr) =>
        pr.head.repo.full_name.toLowerCase() ===
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
  if (args.length === 1 && args[0] === "--help") {
    console.log(
      "Create a pull request after verifying committed HEAD.\nSupported options: --title/-t (required), --body/-b, --body-file/-F, --base/-B, --draft/-d, --no-maintainer-edit",
    );
    return;
  }
  const aliases = new Map([
    ["--title", "title"],
    ["-t", "title"],
    ["--body", "body"],
    ["-b", "body"],
    ["--body-file", "bodyFile"],
    ["-F", "bodyFile"],
    ["--base", "base"],
    ["-B", "base"],
  ]);
  const options = { draft: false, maintainer_can_modify: true };
  for (let i = 0; i < args.length; i++) {
    const [flag] = args[i].split("=");
    if (aliases.has(flag)) {
      const value = args[i].includes("=")
        ? args[i].slice(args[i].indexOf("=") + 1)
        : args[++i];
      if (value === undefined)
        throw new Error(`Missing value for PR flag ${flag}`);
      options[aliases.get(flag)] = value;
    } else if (args[i] === "--draft" || args[i] === "-d") options.draft = true;
    else if (args[i] === "--no-maintainer-edit")
      options.maintainer_can_modify = false;
    else
      throw new Error(
        `Unsupported PR flag ${args[i]}; run make pr ARGS=--help for supported options.`,
      );
  }
  if (!options.title?.trim())
    throw new Error("PR title required; pass --title with a capitalized verb.");
  const branch = run("git", ["symbolic-ref", "--short", "HEAD"]);
  const sha = run("git", ["rev-parse", "HEAD"]);
  const remote = run("git", ["remote", "get-url", "--push", "origin"]);
  const repo = JSON.parse(
    run("gh", [
      "repo",
      "view",
      remote,
      "--json",
      "nameWithOwner,isFork,parent,defaultBranchRef",
    ]),
  );
  const baseRepository = repo.isFork
    ? `${repo.parent.owner.login}/${repo.parent.name}`
    : repo.nameWithOwner;
  let base =
    options.base ??
    run("git", [
      "config",
      "--default",
      "",
      "--get",
      `branch.${branch}.gh-merge-base`,
    ]);
  if (!base) {
    const baseRepo = repo.isFork
      ? JSON.parse(
          run("gh", [
            "repo",
            "view",
            baseRepository,
            "--json",
            "defaultBranchRef",
          ]),
        )
      : repo;
    base = baseRepo.defaultBranchRef.name;
  }
  if (
    baseRepository.toLowerCase() === repo.nameWithOwner.toLowerCase() &&
    branch === base
  )
    throw new Error(
      "PR base and head are the same branch; switch to a feature branch before creating a PR.",
    );
  const body =
    options.bodyFile === undefined
      ? (options.body ?? "")
      : readFileSync(
          options.bodyFile === "-" ? 0 : resolve(root, options.bodyFile),
          "utf8",
        );
  await check(sha);
  if (
    sha !== run("git", ["rev-parse", "HEAD"]) ||
    branch !== run("git", ["symbolic-ref", "--short", "HEAD"])
  )
    throw new Error("HEAD changed during checks; run make pr again.");
  run("git", ["push", "origin", `${sha}:refs/heads/${branch}`], {
    stdio: "inherit",
  });
  run("git", ["config", `branch.${branch}.remote`, "origin"]);
  run("git", ["config", `branch.${branch}.merge`, `refs/heads/${branch}`]);
  const created = JSON.parse(
    run(
      "gh",
      [
        "api",
        `repos/${baseRepository}/pulls`,
        "--method",
        "POST",
        "--input",
        "-",
      ],
      {
        input: JSON.stringify({
          title: options.title,
          body,
          base,
          head: repo.isFork
            ? `${repo.nameWithOwner.split("/")[0]}:${branch}`
            : branch,
          head_repo: repo.nameWithOwner.split("/")[1],
          draft: options.draft,
          maintainer_can_modify: options.maintainer_can_modify,
        }),
      },
    ),
  );
  console.log(created.html_url);
  run("gh", ["pr", "edit", created.html_url, "--add-assignee", "@me"], {
    stdio: "inherit",
  });
  return created.html_url;
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
    if (operation === "install") {
      installHooks(root);
    } else if (operation === "commit") {
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
        "Usage: git-gate.mjs install | commit | push <remote> <url> | pr [options] | check [commit]",
      );
    }
  } catch (error) {
    console.error(
      `Local checks failed; operation stopped. Run make deps for missing tools; run gh auth status for PR lookup failures. For missing gate scripts, update your branch from origin/main. ${error.message}`,
    );
    process.exitCode = 1;
  }
}
