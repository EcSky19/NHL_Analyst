"""Friendly launcher for the Sports Analytics web UI."""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import webbrowser

import uvicorn

from app.config import settings


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url, new=2)
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the Sports Analytics web UI.")
    parser.add_argument("--host", default=settings.host, help=f"Host to bind (default: {settings.host})")
    parser.add_argument("--port", type=int, default=settings.port, help=f"Port to bind (default: {settings.port})")
    parser.add_argument("--reload", action="store_true", help="Restart when Python or UI files change.")
    parser.add_argument("--no-browser", action="store_true", help="Do not try to open the UI in a browser.")
    args = parser.parse_args()

    if _port_in_use(args.host, args.port):
        print(
            f"Port {args.port} is already in use on {args.host}. "
            f"Try: python run_ui.py --port {args.port + 1}",
            file=sys.stderr,
        )
        return 2

    display_host = "localhost" if args.host in {"0.0.0.0", "127.0.0.1"} else args.host
    url = f"http://{display_host}:{args.port}"
    print(f"Starting Sports Analytics UI at {url}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(1.0, _open_browser, args=(url,)).start()

    try:
        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)
    except OSError as exc:
        print(f"Could not start the UI server: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nSports Analytics UI stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
