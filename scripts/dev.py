"""Run the dashboard and its Python API together for local development."""

import argparse
import os
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "3000")))
    args, _ = parser.parse_known_args()
    uvicorn.run("app.main:app", host=args.host, port=args.port)
