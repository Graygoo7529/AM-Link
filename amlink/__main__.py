import argparse
import uvicorn
from pathlib import Path
from .config import load_env_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument('--env-file',type=Path)
    args = parser.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    uvicorn.run("amlink.api:create_app", factory=True, host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
