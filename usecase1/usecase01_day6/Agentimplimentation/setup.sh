#!/usr/bin/env bash
# Environment check for the complaint agents.
#
#   bash setup.sh
#
# What it does:
#   1. Works out which project, region and model to use.
#   2. Writes agents/.env, the settings file the agents read.
#   3. Checks that ADK is installed and that you are signed in.
#   4. Makes one real call to the model, so a permission problem shows up
#      here rather than halfway through the class.
#
# Override any value from the command line, for example:
#   REGION=europe-west2 AGENT_MODEL=gemini-2.5-flash bash setup.sh

set -u
cd "$(dirname "$0")"

PROJECT="${PROJECT:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}}"
REGION="${REGION:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
AGENT_MODEL="${AGENT_MODEL:-gemini-2.5-flash}"

if [ -z "$PROJECT" ] || [ "$PROJECT" = "(unset)" ]; then
  echo "No Google Cloud project is set."
  echo "Run this, using your own project ID, then run setup.sh again:"
  echo "    gcloud config set project <YOUR_PROJECT_ID>"
  exit 1
fi

mkdir -p agents
cat > agents/.env <<ENV
# Written by setup.sh on $(date -u +"%Y-%m-%d %H:%M UTC"). Do not commit this file.
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=$PROJECT
GOOGLE_CLOUD_LOCATION=$REGION
AGENT_MODEL=$AGENT_MODEL
ENV

echo "Project ........ $PROJECT"
echo "Region ......... $REGION"
echo "Model .......... $AGENT_MODEL"

if adk --version >/dev/null 2>&1; then
  echo "ADK ............ OK ($(adk --version 2>/dev/null | head -1))"
else
  echo "ADK ............ MISSING"
  echo "                 Activate the virtual environment and install it:"
  echo "                   source ~/adk-env/bin/activate"
  echo "                   pip install google-adk"
  exit 1
fi

if gcloud auth application-default print-access-token >/dev/null 2>&1; then
  echo "Login .......... OK"
else
  echo "Login .......... NOT FOUND"
  echo "                 Run this, then run setup.sh again:"
  echo "                   gcloud auth application-default login --no-launch-browser"
  exit 1
fi

# The identity that will actually call the model. On a virtual machine this is
# usually the machine's service account, not the account you signed in with.
IDENTITY="$(gcloud config get-value account 2>/dev/null)"
VM_SA="$(curl -s -m 2 -H 'Metadata-Flavor: Google' \
  http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email 2>/dev/null || true)"
if [ -n "$VM_SA" ]; then IDENTITY="$VM_SA"; fi

echo -n "Model access ... "
MODEL_CHECK="$(GOOGLE_CLOUD_PROJECT="$PROJECT" GOOGLE_CLOUD_LOCATION="$REGION" \
  AGENT_MODEL="$AGENT_MODEL" python3 - <<'PY' 2>&1
import os
try:
    from google import genai
    client = genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ["GOOGLE_CLOUD_LOCATION"],
    )
    client.models.generate_content(
        model=os.environ["AGENT_MODEL"], contents="Reply with the word ready."
    )
    print("OK")
except Exception as exc:  # noqa: BLE001
    print(f"FAILED: {type(exc).__name__}: {exc}")
PY
)"

if [ "${MODEL_CHECK}" = "OK" ]; then
  echo "OK"

  # Day 6: the agents reach the data through an MCP server, which needs mcp 1.x.
  printf "MCP support .... "
  MCP_CHECK="$(python3 - <<'PY' 2>&1
import importlib.metadata as m
try:
    version = m.version("mcp")
except m.PackageNotFoundError:
    print("MISSING")
    raise SystemExit
if int(version.split(".")[0]) >= 2:
    print(f"TOO_NEW {version}")
    raise SystemExit
from mcp.server.fastmcp import FastMCP  # noqa: F401
from google.adk.tools.mcp_tool import McpToolset  # noqa: F401
print(f"OK {version}")
PY
)"
  case "$MCP_CHECK" in
    OK*)
      echo "$MCP_CHECK"
      echo "Setup finished."
      exit 0 ;;
    *)
      echo "FAILED ($MCP_CHECK)"
      echo
      echo "The Day 6 agents need ADK's MCP support, with mcp version 1.x. Install it with:"
      echo "    pip install \"google-adk[mcp]\""
      echo "Then run setup.sh again. Do not use a plain 'pip install mcp': that installs"
      echo "version 2, which ADK does not support yet."
      exit 1 ;;
  esac
fi

echo "FAILED"
echo
echo "$MODEL_CHECK" | head -5
echo
echo "The identity this machine uses is: $IDENTITY"
echo
echo "Two ways to fix it."
echo
echo "  1. Ask your admin to grant that identity the Vertex AI User role:"
if [ -n "$VM_SA" ]; then
  echo "       gcloud projects add-iam-policy-binding $PROJECT \\"
  echo "         --member=\"serviceAccount:$IDENTITY\" \\"
  echo "         --role=\"roles/aiplatform.user\""
else
  echo "       gcloud projects add-iam-policy-binding $PROJECT \\"
  echo "         --member=\"user:$IDENTITY\" \\"
  echo "         --role=\"roles/aiplatform.user\""
fi
echo
echo "  2. Or sign in yourself, if your own account already has access:"
echo "       gcloud auth application-default login --no-launch-browser"
echo "       bash setup.sh"
echo
echo "If the error mentions SERVICE_DISABLED, switch the API on first:"
echo "       gcloud services enable aiplatform.googleapis.com --project=$PROJECT"
exit 1
