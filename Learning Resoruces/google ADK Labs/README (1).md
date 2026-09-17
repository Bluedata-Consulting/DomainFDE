# Google ADK 2.0 Graph API Tutorial: Setup Guide

Run every command below in the **VS Code terminal on your Linux VM**, in order.

| Setting | Value |
|---|---|
| Project | `<PROJECT_ID>` |
| Account | `<YOUR_EMAIL>` |
| Model | `gemini-3.5-flash` |
| Region | `global` |
| Folder | `~/adk2-tutorial` |

> **Before you start:** replace every `<PROJECT_ID>` with your Google Cloud project ID and every `<YOUR_EMAIL>` with the Google account you sign in with. Remove the angle brackets too. For example, `<PROJECT_ID>` becomes `my-project-123`.

> **Tip:** open the terminal with **Terminal > New Terminal**. Paste commands with `Ctrl+Shift+V`, then press **Enter**.

---

## Step 1: Check the installed tools

```bash
python3.12 --version && uv --version && gcloud version | head -1
```

All three should print a version. If one says `command not found`, ask your admin to install it.

---

## Step 2: Sign in to Google Cloud

```bash
gcloud auth login <YOUR_EMAIL> --update-adc --no-launch-browser
```

1. Hold **Ctrl** and click the link printed in the terminal.
2. Choose **<YOUR_EMAIL>** and click **Allow**.
3. Copy the verification code, paste it into the terminal, and press **Enter**.

Then set your project:

```bash
gcloud config set project <PROJECT_ID>
gcloud auth application-default set-quota-project <PROJECT_ID>
```

---

## Step 3: Turn on the Gemini API and check access

```bash
gcloud services enable aiplatform.googleapis.com --project=<PROJECT_ID>
```

```bash
gcloud projects get-iam-policy <PROJECT_ID> --flatten="bindings[].members" --filter="bindings.members:user:<YOUR_EMAIL>" --format="value(bindings.role)"
```

You need at least one of `roles/owner`, `roles/editor`, or `roles/aiplatform.user`. If either command fails, send this to your admin:

> Please grant `<YOUR_EMAIL>` the **Vertex AI User** role and enable `aiplatform.googleapis.com` on project `<PROJECT_ID>`.

---

## Step 4: Create the folder, add the files, and create `.env`

```bash
mkdir -p ~/adk2-tutorial && cd ~/adk2-tutorial
```

1. In VS Code click **File > Open Folder...**, type `~/adk2-tutorial/`, click **OK**, and trust the folder.
2. Drag `ADK2_Graph_API_Tutorial.ipynb` and `README.md` into the **Explorer** panel. You do not need to copy `requirements.txt`; Step 5 creates it.
3. Open a new terminal (**Terminal > New Terminal**) and create the settings file:

```bash
cat > ~/adk2-tutorial/.env << 'EOF'
# Use Vertex AI (your Google Cloud project) rather than a personal API key.
GOOGLE_GENAI_USE_VERTEXAI=TRUE

# Your Google Cloud project ID.
GOOGLE_CLOUD_PROJECT=<PROJECT_ID>

# Where the model is called. gemini-3.5-flash is served from the global endpoint.
GOOGLE_CLOUD_LOCATION=global
EOF
```

> **Check:** open `.env` in VS Code and confirm `<PROJECT_ID>` was replaced with your real project ID.

---

## Step 5: Create the Python environment

Create `requirements.txt`, then build the environment and install everything:

```bash
cd ~/adk2-tutorial
cat > requirements.txt << 'EOF'
google-adk>=2.0.0,<3.0.0
google-genai
pydantic
scikit-learn
python-dotenv
ipykernel
ipywidgets
EOF
uv venv --python 3.12 --seed .venv
source .venv/bin/activate
uv pip install -r requirements.txt
adk --version
```

The last line should print `adk, version 2.x.x`. Your prompt now starts with `(.venv)`. Run `source ~/adk2-tutorial/.venv/bin/activate` again whenever you open a new terminal.

Test that ADK and Gemini work:

```bash
adk --version && python -c "from google import genai; c=genai.Client(vertexai=True, project='<PROJECT_ID>', location='global'); print(c.models.generate_content(model='gemini-3.5-flash', contents='Say: setup complete').text)"
```

You should see `adk, version 2.x.x` and then `setup complete`.

---

## Step 6: Run the notebook

1. Open `ADK2_Graph_API_Tutorial.ipynb`.
2. Click **Select Kernel** (top right) > **Python Environments...** > **.venv**.
   If `.venv` is missing: `Ctrl+Shift+P` > **Python: Select Interpreter** > **Enter interpreter path...** > `~/adk2-tutorial/.venv/bin/python`.
3. Go to **0.8 Practical Setup** and run the cells in order with `Shift+Enter`:

| Notebook cell | What to do | You should see |
|---|---|---|
| Step 1: `%pip install` cell | **Skip it** (Step 5 already installed everything) | |
| Step 1: version check | Run | `google-adk 2.x`, plus versions for `google-genai`, `scikit-learn`, `pydantic` (none say `NOT INSTALLED`) |
| Step 2: load `.env` | Run (nothing to edit) | `Project : <PROJECT_ID>`, `Location: global`, `Model   : gemini-3.5-flash` |
| Step 2: credentials check | Run | `ADC credentials found:` |
| Step 2: connectivity test | Run | `Gemini says: project auth works` |
| Step 3: imports | Run | `ADK imports OK. Using gemini-3.5-flash in project <PROJECT_ID> (global)` |
| Step 4: helper utilities | Run | No error |
| Step 5: smoke test | Run | A short, friendly hello from `hello_agent` |

> The markdown text in the notebook may still show an example project ID and `us-central1`. Ignore it; the notebook uses the values from your `.env` file.

4. Continue through Parts 1 to 5 in order.

> After clicking **Restart**, run the setup cells again before continuing.

---

## Every time you come back

1. Open `~/adk2-tutorial` in VS Code and open a terminal.
2. Run `source ~/adk2-tutorial/.venv/bin/activate`
3. Open the notebook, select the `.venv` kernel, and run the **0.8 Practical Setup** cells again (skip `%pip install`).

---

## Troubleshooting

| You see | Do this |
|---|---|
| Prompt does not start with `(.venv)`, or `adk, version 1.x` | `source ~/adk2-tutorial/.venv/bin/activate` |
| `ModuleNotFoundError` or `cannot import name 'Workflow'` in the notebook | Select the `.venv` kernel (Step 6), then click **Restart** |
| Version check shows `NOT INSTALLED`, or `No module named 'sklearn'` | In the terminal run `source ~/adk2-tutorial/.venv/bin/activate && uv pip install -r ~/adk2-tutorial/requirements.txt`, then click **Restart** |
| `GOOGLE_CLOUD_PROJECT is empty` or wrong project/region shown | Check `.env` is in `~/adk2-tutorial` next to the notebook, then click **Restart** |
| Project shows as `<PROJECT_ID>` literally | You forgot to replace the placeholder. Edit `.env`, then click **Restart** |
| `DefaultCredentialsError` or `Reauthentication required` | Repeat Step 2, then click **Restart** |
| `SERVICE_DISABLED` or `PERMISSION_DENIED` | Repeat Step 3, or send the admin message |
| `404 NOT_FOUND` for the model | Make sure `.env` has `GOOGLE_CLOUD_LOCATION=global` (not `us-central1`) and the correct project ID, then click **Restart**. If it still fails, ask your admin to confirm `gemini-3.5-flash` is enabled for the project |
| `DeprecationWarning: GOOGLE_GENAI_USE_VERTEXAI` | Harmless, ignore it |
| `429` or `RESOURCE_EXHAUSTED` | Wait 1 minute and run the cell again |
| Errors only in Parts 3.4 or 3.5 | Google Search may be disabled for your organization. Skip those sections |
| Browser says "Access blocked" when signing in | Ask your admin to allow Google Cloud SDK sign-in |
