from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .config import Config, load_env_file


def main():
    parser = argparse.ArgumentParser(prog="python -m amlink")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    config = Config.from_env()
    if args.host not in {"127.0.0.1", "localhost", "::1"} and config.auth_scheme == "none":
        parser.error("non-loopback bind requires authentication")
    uvicorn.run("amlink.api:create_app", factory=True, host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
