from __future__ import annotations

import argparse
import sys

import uvicorn

from ..config import get_config, set_config
from .api import create_app


def main(argv: list[str] | None = None) -> int:
    import os

    parser = argparse.ArgumentParser(description="AGENT_Joko Dashboard")
    parser.add_argument(
        "--host",
        default=os.environ.get("HOST", "127.0.0.1"),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8000")),
    )
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    config = get_config()
    # Ensure config knows our workspace root (cwd where the process is launched).
    # Pinokio launches from the project root, so '.' is correct.
    config.workspace_root = "."
    # Keep all state inside the project folder (Pinokio-friendly, avoids home-dir permissions).
    from pathlib import Path

    config.memory.storage_path = str((Path.cwd() / ".devin_agent" / "memory").resolve())
    set_config(config)

    app = create_app(config=config)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
