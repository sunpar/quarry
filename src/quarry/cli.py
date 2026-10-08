"""Command line entry: `quarry serve`."""

from __future__ import annotations

import argparse
import secrets
import socket
import sys
from pathlib import Path

import uvicorn

from quarry.config import load_config
from quarry.server.app import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quarry")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="start the Quarry server on loopback")
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--root", type=Path, default=Path("~/.quarry"))
    serve.add_argument("--host-hint", default=socket.gethostname())
    args = parser.parse_args(argv)
    if args.command != "serve":
        parser.print_usage(sys.stderr)
        return 2
    return run_serve(
        port=args.port or free_port(), root=args.root.expanduser(), host_hint=args.host_hint
    )


def run_serve(*, port: int, root: Path, host_hint: str) -> int:
    root.mkdir(parents=True, exist_ok=True)
    token = new_token()
    app = create_app(config=load_config(root), token=token)
    print(banner(port=port, token=token, host_hint=host_hint), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
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
