"""Central config: read everything from environment variables (no hard-coded keys)."""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load variables from a local .env file (no-op if the file is absent).
load_dotenv()

# --- Paths ---------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent # src/../ 
DATA_DIR = ROOT_DIR / "data"
ARTICLES_DIR = DATA_DIR / "articles"
LOGS_DIR = ROOT_DIR / "logs"

# --- Secrets / runtime config (from env) ---------------------------------
# Generic name so it works for OpenAI or Gemini (per the brief).
API_KEY = os.getenv("API_KEY")

# Reuse an existing Gemini File Search Store across daily runs; created on first run if empty.
FILE_SEARCH_STORE_NAME = os.getenv("FILE_SEARCH_STORE_NAME")

# Zendesk Help Center base for OptiSigns support articles.
ZENDESK_BASE_URL = os.getenv(
    "ZENDESK_BASE_URL", "https://support.optisigns.com/api/v2/help_center"
)

# Max articles to scrape per run. The brief requires >= 30; default 40 leaves
# headroom. Set MAX_ARTICLES=0 (or negative) to pull every published article.
MAX_ARTICLES = int(os.getenv("MAX_ARTICLES", "40"))


def require(name: str, value):
    """Fail fast with a clear message if a required env var is missing."""
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# --- Logging -------------------------------------------------------------
# Log level is env-driven so we can bump to DEBUG in a container without a code
# change: LOG_LEVEL=DEBUG docker run ...
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


def setup_logging() -> None:
    """Configure root logging once, at process entry point.

    Streams to stdout (not stderr) so Docker/schedulers capture the run output on
    the standard channel. Called from main.py and from each module's standalone
    __main__ block; library modules themselves only call getLogger() and never
    configure handlers. force=True makes a second call (e.g. standalone run that
    also imports a module) reset handlers instead of stacking duplicates.
    """
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        stream=sys.stdout,
        force=True,
    )
