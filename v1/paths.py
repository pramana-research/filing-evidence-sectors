"""Where the SEC filings live (only the dataset build reads them): DATA_DIR from .env or the environment."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[1] / ".env")  # repo root (this file is a v1 copy in v1/)


def data_dir() -> Path:
    p = Path(os.environ.get("DATA_DIR", Path(__file__).parents[1] / "data")).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p
