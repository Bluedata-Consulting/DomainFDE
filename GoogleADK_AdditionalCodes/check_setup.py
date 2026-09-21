"""Pre-flight check for the lab. Run:  python check_setup.py

Tells you in plain words whether auth works, and exactly what to do if not.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

OK, BAD = "  [OK]  ", "  [FAIL]"
ADC = Path.home() / ".config/gcloud/application_default_credentials.json"


def main() -> int:
    print("\n=== Lab setup check ===\n")

    # 1. Packages
    try:
        import google.adk, chromadb, rank_bm25  # noqa: F401
        print(OK, f"google-adk {google.adk.version.__version__}, chromadb, rank-bm25 installed")
    except ImportError as e:
        print(BAD, f"missing package: {e}")
        print("        fix: source .venv/bin/activate && pip install -r requirements.txt")
        return 1

    # 2. .env
    vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").upper() == "TRUE"
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    if vertex and project:
        print(OK, f".env -> Vertex AI, project={project}, location={location}")
    elif os.environ.get("GOOGLE_API_KEY"):
        print(OK, ".env -> AI Studio API key")
    else:
        print(BAD, ".env has neither Vertex settings nor GOOGLE_API_KEY")
        return 1

    # 3. ADC file freshness (Vertex only)
    if vertex:
        if ADC.exists():
            age_days = (datetime.now() - datetime.fromtimestamp(ADC.stat().st_mtime)).days
            mtime = datetime.fromtimestamp(ADC.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            print(OK if age_days < 1 else BAD, f"ADC file last written {mtime} ({age_days} days ago)")
        else:
            print("  [--]  ", "no ADC file; will fall back to VM service account")

    # 4. The real test: one model call
    print("\n  calling gemini-2.5-flash ...")
    try:
        from google import genai
        client = genai.Client(vertexai=True, project=project, location=location) if vertex else genai.Client()
        text = client.models.generate_content(model="gemini-2.5-flash", contents="Reply with the single word OK").text
        print(OK, f"model replied: {text.strip()!r}")
    except Exception as e:  # noqa: BLE001
        msg = str(e).splitlines()[-1]
        print(BAD, f"model call failed: {msg[:160]}")
        if "Reauthentication" in msg or "RefreshError" in type(e).__name__:
            print("\n        Your login has expired. Run this EXACT command (note 'application-default'):")
            print("            gcloud auth application-default login --no-launch-browser")
            print("        answer Y, open the link, paste the code back, and wait for:")
            print("            'Credentials saved to file: ...'")
        return 1

    print("\n=== ALL GOOD - you can run the labs ===\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
