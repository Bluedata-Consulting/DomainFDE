# Day 7 · Use case 1: operate the agent, and the fire drill

The agent is live. Today you **operate** it: release it as one versioned unit, watch what
it does, and get it back quickly when something goes wrong. Then someone breaks it on
purpose.

One agent runs in production today, `v7_operations`: the Day 5 team with the Day 6
grounded assistant inside it.

| Specialist | Does | From |
|---|---|---|
| `complaints_agent` | The customer conversation: apologies, consent, vulnerable customers | Day 5 |
| `returns_agent` | Where returned items go, and vendor claims | Day 5 |
| `billing_agent` | Refunds, and approvals above the limit | Day 5 |
| `knowledge_agent` | Answers from records (SQL) and policies (RAG), over MCP. Changes nothing | Day 6 |

What is new is everything around it:

| Part | What it does |
|---|---|
| **Releases** (`releases/`, `ops/release.py`) | Model, instructions, policies and tool settings, versioned together, with fingerprints |
| **Tracing** | Every model and tool call in the `adk web` Trace tab, stamped with its release |
| **Health check** (`ops/check.py`) | A behaviour contract, plus SLIs measured against SLOs |
| **Graceful degradation** | A failed tool is retried twice, then reported, never guessed around |
| **Fire drill** (`ops/fire_drill.py`) | Deploys a release with a hidden fault, for you to find and roll back |

Read in this order:

1. `usecase1_day7_problem_statement.pdf`: the business case. A week in production, and why
   the agent can change with no code change at all.
2. `usecase1_day7.pdf`: the practical. What was built, your task and the seven questions.

Record everything in `Day7_Worksheets_UC01.docx`.

Fill in `<YOUR_GOOGLE_ACCOUNT>` and `<YOUR_PROJECT_ID>` wherever they appear. Everything
else pastes as written. You work in a terminal on **your VM**; the browser is the one
on the VM too. Using the shared training account? Follow `README-training-account.md`
instead: it is this page, pre-filled.

The code lives in this repository under `usecase1/usecase01_day7/Agentimplementation/`. The
commands below set one variable, `$KIT`, pointing at that folder, and use it everywhere.

---

## Setup: first time only

If you completed setup on this VM for an earlier day, with the same account and project,
steps 1 to 4 and 6 are already done. Do steps 5, 6b and 7, then carry on at step 8.

### 1. Open a terminal on the VM

Open the terminal application on the VM desktop (or the terminal panel in
code-server). Every command below goes here.

### 2. Sign in to Google Cloud

Two sign-ins, because two things need to prove who you are: the `gcloud` command,
and the agents themselves.

```bash
gcloud auth login --no-launch-browser
```

Copy the link it prints into the browser on the VM, sign in as
`<YOUR_GOOGLE_ACCOUNT>`, and paste the code back into the terminal.

```bash
gcloud auth application-default login --no-launch-browser
```

Same again. This second login is the one the agents use when they call the model.

### 3. Set your account and project

```bash
gcloud config set account <YOUR_GOOGLE_ACCOUNT>
gcloud config set project <YOUR_PROJECT_ID>
gcloud config list
```

> **Expected:** the last command shows your account and your project ID.

### 4. Enable Vertex AI

```bash
gcloud services enable aiplatform.googleapis.com --project=<YOUR_PROJECT_ID>
```

Silence means success. If it says `PERMISSION_DENIED`, check whether it is already
on, then move on:

```bash
gcloud services list --enabled --project=<YOUR_PROJECT_ID> | grep aiplatform
```

### 5. Get the repository and point at the kit

**5a. Get the code.** Do the one that matches your VM.

First time on this VM (no `~/domainFDE` folder yet):

```bash
cd ~
git clone https://github.com/Bluedata-Consulting/DomainFDE.git domainFDE
```

Already cloned for an earlier day? Update it, so you get the Day 7 folder:

```bash
cd ~/domainFDE
git pull
```

**5b. Set the variable every command below relies on**, and make it stick for new
terminals:

```bash
echo 'export KIT="$HOME/domainFDE/usecase1/usecase01_day7/Agentimplementation"' >> ~/.bashrc
source ~/.bashrc
echo $KIT
ls "$KIT/setup.sh"
ls "$KIT/agents"
```

> **Expected:**
> ```
> /home/<you>/domainFDE/usecase1/usecase01_day7/Agentimplementation
> /home/<you>/domainFDE/usecase1/usecase01_day7/Agentimplementation/setup.sh
> v7_operations
> ```
> A `1.md` file may be listed next to `v7_operations`. It is a placeholder, and ADK ignores it.

**5c. Only if `ls "$KIT/setup.sh"` says `No such file or directory`.** Your
`~/domainFDE` folder does not match GitHub. Usually it was unzipped or copied rather
than cloned, it came from somewhere else, or `git pull` stopped on local files. Check:

```bash
cd ~/domainFDE
git remote -v
git log -1 --format='%h %cd %s'
ls ~/domainFDE/usecase1/usecase01_day7
```

> **Healthy:** the remote is `https://github.com/Bluedata-Consulting/DomainFDE.git`, and
> `ls` shows `Agentimplementation`, both READMEs, `ARCHITECTURE.md`,
> `usecase1_day7_problem_statement.pdf`, `usecase1_day7.pdf` and the worksheet.

If any of that differs, or a command prints an error such as `not a git repository`,
`would be overwritten` or `diverged`, keep the old folder aside and take a fresh copy:

```bash
cd ~
mv domainFDE domainFDE_old
git clone https://github.com/Bluedata-Consulting/DomainFDE.git domainFDE
source ~/.bashrc
ls "$KIT/setup.sh"
```

> **Expected:** the path to `setup.sh` is printed. Once everything works, you can delete
> the old copy with `rm -rf ~/domainFDE_old`.

Still missing? Put your hand up, and show the output of the check commands above.

### 6. Activate the ADK environment

```bash
source ~/adk-env/bin/activate
adk --version
```

> **Expected:** `(adk-env)` at the start of your prompt and a version number.

If `adk-env` does not exist:

```bash
python3 -m venv ~/adk-env
source ~/adk-env/bin/activate
pip install google-adk
adk --version
```

You will need `source ~/adk-env/bin/activate` again in every **new** terminal. Today
every command needs it, including the tests.

**6b. Add ADK's MCP support.** The knowledge agent reaches the data through an MCP
server, which needs the `mcp` package, version 1.x:

```bash
pip install "google-adk[mcp]"
python3 -c "import importlib.metadata as m; print('mcp', m.version('mcp'))"
```

> **Expected:** `mcp 1.` followed by a version number, such as `mcp 1.30.0`.
>
> Do **not** use a plain `pip install mcp`. That installs version 2, which renamed its
> server API and which ADK does not support yet. If you already did, fix it with
> `pip install "mcp>=1.24,<2"`.

### 7. Run the setup check

```bash
bash "$KIT/setup.sh"
```

It writes `usecase1/usecase01_day7/Agentimplementation/agents/.env` (your project, region and
model) and makes one real call to the model, so any access problem shows up here rather
than in the exercise.

> **Expected:** `Model access ... OK`, then `MCP support .... OK 1.x.x`, and `Setup finished.`
>
> If MCP support says `FAILED`, it prints the command that fixes it. That is step 6b.

If model access **failed**, the script prints which identity was refused and the
command that fixes it. Usually it is one of these:

```bash
# you skipped the second login in step 2
gcloud auth application-default login --no-launch-browser
bash "$KIT/setup.sh"

# your account lacks the Vertex AI User role: hand up; the coach grants it
gcloud projects add-iam-policy-binding <YOUR_PROJECT_ID> \
  --member="user:<YOUR_GOOGLE_ACCOUNT>" --role="roles/aiplatform.user"
```

---

## Look inside (no model)

Fill in the prediction page of the worksheet **before** this part.

### 8. Run every component test

```bash
source ~/adk-env/bin/activate
cd "$KIT"
bash tests/check_parts.sh
```

> **Expected:** five blocks, then the verdict.
> ```
>   Releases and the fire drill      23 of 23 checks passed.
>   The rules and the router         16 of 16 checks passed.
>   The grounding parts              21 of 21 checks passed.
>   The metrics                      5 of 5 metrics matched.
>   The ontology                     ALL CHECKS PASSED
>
> ALL PARTS PASS. The release is worth deploying.
> ```

This is the first half of the **release gate**: nothing is promoted unless every part passes.

### 9. Read the release

```bash
python3 -m ops.release list
python3 -m ops.release show
cat releases/r1/release.yaml | head -12
```

> **Expected:**
> ```
>      Release   Status        Model                   Notes
>   -> r1        current       gemini-2.5-flash        First production release: ...
>
>   Release r1  (current)  created 2026-09-22 09:00 UTC
>   ...
>   17 files fingerprinted
>   Drift: none. The release matches its fingerprints.
> ```

`releases/r1/` holds everything that shapes behaviour: `instructions/`, `policies/`, and
`release.yaml` with the model and tool settings. The agents read all of it from the
**current** release, named in `releases/CURRENT`.

### 10. Make a drift, and undo it

Edit a released file without making a release, as someone "just tidying the wording" would:

```bash
echo "# tidied" >> releases/r1/instructions/complaints.txt
python3 -m ops.release show | tail -3
```

> **Expected:**
> ```
>   DRIFT: changed since the release was made, outside any release:
>     instructions/complaints.txt
> ```

The fingerprints caught it. Undo it before going on:

```bash
git checkout -- releases/r1/instructions/complaints.txt
python3 -m ops.release show | tail -2
```

> **Expected:** `Drift: none. The release matches its fingerprints.`

---

## Run it, and watch it

### 11. Start the chat server, and read a trace

```bash
source ~/adk-env/bin/activate
cd "$KIT/agents"
adk web
```

> **Expected:** `Uvicorn running on http://127.0.0.1:8000`

In the browser, go to **http://127.0.0.1:8000**, choose `v7_operations`, click **New
Session**, and send:

```
Complaint C-106: the kettle is cracked, the customer wants their money back, and it came back as return R-206. Sort it all out.
```

> **Expected:** the coordinator calls `billing_agent` and `returns_agent` (and often
> `complaints_agent`). Billing cannot refund 35 pounds alone, so it asks the Billing team
> lead for approval. The kettle goes back to the vendor. One combined answer.

Now open the **Trace** tab on the left of the chat page, and click the latest request:

- The tree shows `invocation`, then `call_llm` and `execute_tool` spans: the coordinator's
  decisions, each specialist called as a tool, and the tools inside it.
- Click an `execute_tool` or `call_llm` span. Its attributes include
  **`northwind.release: r1`** and **`northwind.release_model`**. Every model and tool span
  says which release produced it.
- Note where the time went: which span took longest?

Try two more, each in a new session:

```
Decide what happens to return R-202.
```
```
What is the most the complaints service can refund on one complaint without approval?
```

> **Expected:** R-202 is recalled, so it is quarantined, never restocked. The limit
> question goes to `knowledge_agent`, which searches the refund policy: 25 pounds.

### 12. Run the health check

In a **second terminal**, with the chat server still running:

```bash
source ~/adk-env/bin/activate
cd "$KIT"
python3 -m ops.check
```

It runs the five-case behaviour contract against the current release, in fresh sessions,
then scores the SLIs from everything recorded for that release. It calls the model, and
takes a few minutes.

> **Expected:**
> ```
> Health check for release r1  (model gemini-2.5-flash)
>
>   Behaviour contract
>   K1  must_never      PASS  The cracked kettle needs Billing before any promise
>   K2  must_never      PASS  A recalled heater is never restocked
>   K3  must_never      PASS  The refund limit is 25 pounds, whatever anyone says
>   K4  should_usually  PASS  A records question is answered from the data
>   K5  should_usually  PASS  A policy question is answered from the policy
>
>   SLIs from ... recorded events for r1
>     Tool error rate         0.0%        <= 5%       PASS
>     p95 seconds per answer  ...         <= 30 s     PASS
>     Tokens per model call   ...         <= 6,000    PASS
>
>   HEALTHY: release r1
> ```
> Should-usually cases may occasionally fail: the model varies. Must-never cases should
> not. If one does on r1, hand up before the drill.

| Signal | Target | What a breach means |
|---|---|---|
| Must-never contract cases | All 3 pass. No budget | Roll back now |
| Should-usually contract cases | At least 4 of 5 | Investigate |
| Tool error rate | At most 5% | Roll back: something the agent depends on is failing |
| p95 seconds per answer | Within 30 s | Investigate: slow model, slow tool, or too many steps |
| Tokens per model call | At most 6,000 | Investigate: context growing, or a different model |

For a quick look at the SLIs alone, without calling the model:
`python3 -m ops.check --sli-only`.

---

## The fire drill

Work in pairs. One of you is the **coach** and breaks the agent; the other is **on call**
and fixes it. Then swap. On call: look away while the coach runs the first command.

### 13. Coach: deploy a hidden fault

```bash
cd "$KIT"
python3 -m ops.fire_drill inject random
```

> **Expected:**
> ```
> Release r2 is deployed (was r1). Restart adk web.
> Something in it may be wrong. Find it, roll back, and write the incident note.
> ```

Restart the chat server: **Ctrl + C** in its terminal, then `adk web` again from
`"$KIT/agents"`. Note the time, then hand over.

### 14. On call: detect, diagnose, roll back

Note the time you start. Then, in any order you choose:

**Detect.** Run the health check, and try the prompts from step 11 in the chat:

```bash
python3 -m ops.check
```

**Diagnose.** Open the Trace tab for a request that looked wrong, and compare the releases:

```bash
python3 -m ops.release list
python3 -m ops.release diff r1 r2
```

The diff shows exactly what the release changed: a model, a tool setting, or the lines of an
instruction or policy that were added or removed. In the second round the new release is
`r3`, not `r2`: use the tags that `list` shows.

**Roll back** when you are sure:

```bash
python3 -m ops.release rollback
```

> **Expected:** `Rolled back: r2 -> r1. Restart adk web to run it.` (or `r3 -> r1` in the second round)

Restart the chat server, then confirm the recovery:

```bash
python3 -m ops.check
```

> **Expected:** `HEALTHY: release r1`. Note the time: that is your **time to recover**.

**What each kind of fault usually looks like**, for after you have tried:

| Fault | Health check | Trace and terminal | Release diff |
|---|---|---|---|
| A tool stops responding | Contract often **passes**: the agent recovers politely. The **tool error rate** breaches | `>>> TOOL FAILED: get_refunds` in the chat terminal; the error in the span's result | `tool_settings: get_refunds: timeout` |
| A prompt line removed | K1 often fails: Billing is not called first, or money is promised | A path that skips `billing_agent` | The removed lines, marked `-` |
| The model is swapped | Contract may pass. Time and tokens may change | `northwind.release_model` on each span | `model: gemini-2.5-flash -> ...` |
| A policy edited | K3 fails: the answer says 50 pounds | `knowledge_agent`'s `search_policy` returns the new text | The changed lines of `refunds.md` |

The coach can confirm what was injected: `python3 -m ops.fire_drill reveal`.

### 15. Write the incident note

Add one line to `ops/incident_note.md`: when, which release, what broke, the impact, how you
found it, the fix, and the follow-up. Then swap roles and run steps 13 to 15 again.

```bash
cat releases/HISTORY.log
```

> **Expected:** every deploy and rollback, with its time. Your evidence for the note.

### 16. The plan, architecture v2 and the seven questions

Write the one-page deployment, monitoring and rollback plan on the worksheet, draw
architecture v2 (observability, versioning and rollback around the agent), and answer the
seven questions in `usecase1_day7.pdf`.

---

## Reset after the drill

The drill leaves extra releases behind. To go back to exactly what was shipped:

```bash
cd "$KIT"
git checkout -- releases/
git clean -fd releases/
python3 -m ops.release list
```

> **Expected:** only `r1`, and it is current. Restart `adk web` afterwards.

---

## Stop the chat server

**Normally:** press **Ctrl + C** in the terminal running `adk web`. The MCP server it started
stops with it.

**If that terminal is gone, or the port is still busy**, find the server and stop it:

```bash
pgrep -af "bin/adk"
pkill -f "bin/adk"
pgrep -af "bin/adk" || echo "no server running"
```

> **Expected:** the first command prints one line like
> `/usr/bin/python3 /usr/local/bin/adk web`, and the last prints `no server running`.
>
> Run these in a normal terminal, one at a time. Do not paste them into a script: a script
> whose own command line contains the pattern can match itself.

If an MCP server is left running on its own:

```bash
pgrep -af northwind_mcp || echo "no MCP server running"
pkill -f northwind_mcp
```

**Clear the saved chat sessions too**, so an old conversation does not reappear:

```bash
rm -rf "$KIT"/agents/*/.adk
```

---

## If something breaks

Put your hand up first. Do not spend the session fixing the environment.

| Symptom | Likely cause | Fix |
|---|---|---|
| `No such file or directory` for `usecase1/usecase01_day7` or `setup.sh` | Repository not updated, or `~/domainFDE` is not a clone of GitHub | `cd ~/domainFDE && git pull`; if still missing, step 5c (fresh clone) |
| `git pull` prints `not a git repository`, `would be overwritten` or `diverged` | The folder was unzipped, copied or edited | Step 5c: move it aside and clone again |
| `git pull` says local changes would be overwritten in `releases/` | A drill was not reset | "Reset after the drill", then `git pull` |
| `$KIT` points to the wrong folder, such as an earlier day | An older `export KIT` line is used | Repeat the `echo` line in step 5b, then `source ~/.bashrc` and `echo $KIT` |
| `ModuleNotFoundError: No module named 'mcp'`, or a message about `MCPServer` | MCP support missing, or `mcp` version 2 | Step 6b: `pip install "google-adk[mcp]"` |
| `ModuleNotFoundError: No module named 'yaml'`, `'google'`, `'northwind'` or `'ops'` | ADK environment not active, or not run from `$KIT` | `source ~/adk-env/bin/activate`, `cd "$KIT"`, then run it again |
| `v7_operations` missing from the drop-down | Server started from the wrong folder | `Ctrl + C`, `cd "$KIT/agents"`, start again |
| The chat still behaves like the old release | `adk web` was not restarted after a deploy or rollback | Restart it: the agents read their release when they start |
| No **Trace** tab, or it is empty | No request sent yet in this session | Send a message, then open the Trace tab |
| `WARNING: the release has drifted` in the health check | A released file was edited directly | `git checkout -- releases/`, or make the change as a new release |
| The model fault fails with a model not found error | `gemini-2.5-flash-lite` is not available in your project | Record it as the fault: the release broke the agent. Roll back |
| `No good release to roll back to` | Every release was rolled back or broken | "Reset after the drill" |
| `PERMISSION_DENIED` / `403` in the reply | Identity cannot call Vertex AI | `bash "$KIT/setup.sh"` and follow what it prints |
| `A PART FAILED` in step 8 | A file was changed | `cd "$KIT" && git checkout -- .` |
| `git status` lists `runs.jsonl`, `escalations.log` or `data/northwind.db` | The repository has no `.gitignore` for the kit | Leave them; never `git add` them. They are created by running the agents |
| `git clean -fd releases/` offers to delete something you wrote | You saved work inside `releases/` | Move it out of `releases/` first, then reset |
| Port 8000 already in use | Old chat server still running | `pkill -f "bin/adk"`, or `adk web --port 8001`. See "Stop the chat server" |

---

## How Day 7 differs from Day 6

| | Day 6 | Day 7 |
|---|---|---|
| **What you change** | Files, directly | A new release, checked, promoted, and rolled back if needed |
| **What you know about an answer** | The source it cited | The source, and the exact release (model, instructions, policies) behind it |
| **When a tool fails** | The answer fails | It is retried, reported, and counted against an error budget |
| **Proof** | A before and after score | A health check, a trace, a release history, and an incident note |

Nothing the agent does is new today. What is new is that you can say which version did it,
notice within minutes when it stops doing it, and put it back.
