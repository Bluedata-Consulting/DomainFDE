"""Environment and model configuration.

Kept in one place so that switching from AI Studio to Vertex AI, or upgrading a
model, is a single-line change rather than a search-and-replace across the repo.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the repository root (one level up from this example folder).
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# --- Models ---------------------------------------------------------------
# Flash is the correct default: this workload is extraction + drafting, not
# open-ended reasoning, and it runs on every inbound ticket.
FLASH = "gemini-2.5-flash"
PRO = "gemini-2.5-pro"

APP_NAME = "aurora_ex04_single_agent_tools"
USER_ID = "ops_user_001"

DATA_DIR = Path(__file__).parent / "data"


def verify_credentials() -> None:
    """Fail fast with a useful message instead of a 401 deep inside the SDK."""
    use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "FALSE").upper() == "TRUE"

    if use_vertex:
        if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
            raise RuntimeError(
                "GOOGLE_GENAI_USE_VERTEXAI=TRUE but GOOGLE_CLOUD_PROJECT is not set. "
                "Set it in .env and run: gcloud auth application-default login"
            )
        return

    if not os.environ.get("GOOGLE_API_KEY"):
        raise RuntimeError(
            "GOOGLE_API_KEY is not set. Copy .env.example to .env and add your key "
            "from https://aistudio.google.com/apikey"
        )
