"""Central config: read everything from environment variables (no hard-coded keys)."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load variables from a local .env file (no-op if the file is absent).
load_dotenv()

# --- Paths ---------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
ARTICLES_DIR = DATA_DIR / "articles"
STATE_FILE = DATA_DIR / "state.json"
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

# Minimum articles required by the brief.
MIN_ARTICLES = int(os.getenv("MIN_ARTICLES", "30"))


def require(name: str, value):
    """Fail fast with a clear message if a required env var is missing."""
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value
