"""Command line entry: `quarry serve` and `quarry projects list|export`."""

from __future__ import annotations

import argparse
import secrets
import socket
import sys
from pathlib import Path

import uvicorn

from quarry.config import load_config
from quarry.projects.export import notebook_json
from quarry.projects.store import ProjectStore
from quarry.server.app import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quarry")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="start the Quarry server on loopback")
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--root", type=Path, default=Path("~/.quarry"))
    serve.add_argument("--host-hint", default=socket.gethostname())
    projects = sub.add_parser("projects", help="list or export saved projects")
    project_sub = projects.add_subparsers(dest="project_command")
    # On each leaf parser, so `quarry projects list --root X` parses: argparse hands the
    # remaining arguments to the leaf, which must know the option.
    with_root = argparse.ArgumentParser(add_help=False)
    with_root.add_argument("--root", type=Path, default=Path("~/.quarry"))
    project_sub.add_parser("list", parents=[with_root], help="list projects under the root")
    export = project_sub.add_parser(
        "export", parents=[with_root], help="write a project as a Jupyter notebook"
    )
    export.add_argument("slug")
    export.add_argument("--out", type=Path, default=None, help="defaults to <slug>.ipynb here")
    args = parser.parse_args(argv)
    if args.command == "serve":
        return run_serve(
            port=args.port or free_port(), root=args.root.expanduser(), host_hint=args.host_hint
        )
    if args.command == "projects" and args.project_command == "list":
        return run_projects_list(root=args.root.expanduser())
    if args.command == "projects" and args.project_command == "export":
        return run_projects_export(root=args.root.expanduser(), slug=args.slug, out=args.out)
    parser.print_usage(sys.stderr)
    return 2


def run_serve(*, port: int, root: Path, host_hint: str) -> int:
    # Private when new: it holds every session's prompts and code. An existing root keeps its mode.
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    token = new_token()
    app = create_app(config=load_config(root), token=token)
    print(banner(port=port, token=token, host_hint=host_hint), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


def run_projects_list(*, root: Path) -> int:
    for meta in ProjectStore(root).list():
        print(f"{meta.slug}\t{meta.name}\t{meta.updated_at}")
    return 0


def run_projects_export(*, root: Path, slug: str, out: Path | None) -> int:
    store = ProjectStore(root)
    try:
        project = store.get(slug)
    except KeyError:
        print(f"no such project: {slug}", file=sys.stderr)
        return 1
    target = out if out is not None else Path(f"{slug}.ipynb")
    target.write_text(notebook_json(project, store), encoding="utf-8")
    print(f"wrote {target}")
    return 0


def banner(*, port: int, token: str, host_hint: str) -> str:
    return (
        f"Quarry is running on 127.0.0.1:{port}\n\n"
        "1. On your desktop, open a tunnel:\n"
        f"   ssh -L {port}:127.0.0.1:{port} {host_hint}\n"
        "2. Then open:\n"
        f"   http://127.0.0.1:{port}/#token={token}\n\n"
        f"Token (keep private): {token}\n"
    )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


def new_token() -> str:
    return secrets.token_urlsafe(32)


if __name__ == "__main__":
    raise SystemExit(main())
