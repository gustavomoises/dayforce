"""Load settings from environment variables (and the local .env file)."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

load_dotenv(PROJECT_ROOT / ".env")


def get_setting(name: str, default: str | None = None) -> str:
    """Return an environment variable, or raise if it is missing and has no default."""
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Missing required setting: {name} (set it in .env)")
    return value
