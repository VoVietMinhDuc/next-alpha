"""Central config: read everything from environment variables (no hard-coded keys)."""

import os
from pathlib import Path

# --- Paths ---------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
ARTICLES_DIR = DATA_DIR / "articles"
STATE_FILE = DATA_DIR / "state.json"
LOGS_DIR = ROOT_DIR / "logs"

# --- Secrets / runtime config (from env) ---------------------------------
# Generic name so it works for OpenAI or Gemini (per the brief).
API_KEY = os.getenv("API_KEY")

# Reuse an existing vector store across daily runs; created on first run if empty.
VECTOR_STORE_ID = os.getenv("VECTOR_STORE_ID")

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
