# Day 6 · Use case 1: ground the agent in real data and policies

Until today the agent answered from its instruction, its tool descriptions and one record
at a time. Ask it about a policy, or about many records at once, and it could only guess.
Today it is **grounded**: it answers from Northwind's own records and policies, reached
through an **MCP server** that owns them.

| Technique | What it does here |
|---|---|
| **RAG** | `search_policy` finds the passages of six policy documents most relevant to a question |
| **NLP2SQL** | `describe_data` and `run_sql` turn a question into one read-only SQL query |
| **MCP** | One Northwind server offers all three tools. The agents connect to it; they never touch the data directly |

The experiment is three agents answering the same ten questions:

| Agent | Sees | Role |
|---|---|---|
| `v6_ungrounded` | Nothing but its instruction | **Before**: what the model knows on its own |
| `v6_grounded_raw` | Raw tables and the policies, over MCP | **Run 1** |
| `v6_grounded_semantic` | Ontology-aligned views and the policies, over MCP | **Run 2**: only the shape of the data changed |

Read in this order:

1. `usecase1_day6_problem_statement.pdf`: the business case. Why people need trusted,
   sourced answers from records and policies owned by different teams.
2. `usecase1_day6.pdf`: the practical. What was built, your task and the seven questions.
3. `ARCHITECTURE.md`, when you want to know how the pieces fit together.

Record everything in `Day6_Worksheets_UC01.docx`.

Fill in `<YOUR_GOOGLE_ACCOUNT>` and `<YOUR_PROJECT_ID>` wherever they appear. Everything
else pastes as written. You work in a terminal on **your VM**; the browser is the one
on the VM too. Using the shared training account? Follow `README-training-account.md`
instead: it is this page, pre-filled.

The code lives in this repository under `usecase1/usecase01_day6/Agentimplementation/`. The
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

Already cloned for an earlier day? Update it, so you get the Day 6 folder:

```bash
cd ~/domainFDE
git pull
```

**5b. Set the variable every command below relies on**, and make it stick for new
terminals:

```bash
echo 'export KIT="$HOME/domainFDE/usecase1/usecase01_day6/Agentimplementation"' >> ~/.bashrc
source ~/.bashrc
echo $KIT
ls "$KIT/setup.sh"
ls "$KIT/agents"
```

> **Expected:**
> ```
> /home/<you>/domainFDE/usecase1/usecase01_day6/Agentimplementation
> /home/<you>/domainFDE/usecase1/usecase01_day6/Agentimplementation/setup.sh
> v6_grounded_raw  v6_grounded_semantic  v6_ungrounded
> ```

**5c. Only if `ls "$KIT/setup.sh"` says `No such file or directory`.** Your
`~/domainFDE` folder does not match GitHub. Usually it was unzipped or copied rather
than cloned, it came from somewhere else, or `git pull` stopped on local files. Check:

```bash
cd ~/domainFDE
git remote -v
git log -1 --format='%h %cd %s'
ls ~/domainFDE/usecase1/usecase01_day6
```

> **Healthy:** the remote is `https://github.com/Bluedata-Consulting/DomainFDE.git`, and
> `ls` shows `Agentimplementation`, both READMEs, `ARCHITECTURE.md`,
> `usecase1_day6_problem_statement.pdf` and `usecase1_day6.pdf`.

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

**6b. Add ADK's MCP support (new today).** The Day 6 agents reach the data through an MCP
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

It writes `usecase1/usecase01_day6/Agentimplementation/agents/.env` (your project, region and
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

## Look inside the grounding (no model)

Fill in the prediction page of the worksheet **before** this part.

### 8. Build the database

```bash
source ~/adk-env/bin/activate
cd "$KIT"
python3 -m northwind.database
```

> **Expected:**
> ```
>   cust_tbl       5 rows
>   acc_tbl        6 rows
>   ...
>   rtn_tbl        5 rows
>   cons_tbl       13 rows
>   complaints_v   6 rows
>   returns_v      5 rows
>   refunds_v      2 rows
>   consents_v     13 rows
>
> Built data/northwind.db
> ```

The same records, in two shapes: seven **raw tables** as a back-office system might store
them, and four **views** on top, the semantic layer. The agents build the database
themselves if it is missing; building it here lets you look at it.

### 9. Run every component test

```bash
bash tests/check_parts.sh
```

> **Expected:** two blocks, then the verdict.
> ```
>   PASS  G1 vulnerable complaints, from the semantic view    ... got ['C-103', 'C-105']
>   PASS  G1 trap: the raw account flag finds none            ... got []
>   PASS  G4 grade C returns                                  ... got [3]
>   PASS  G4 trap: raw grades are codes, not letters          ... got [0]
>   ...
>   PASS  The semantic server offers three tools              ... ['describe_data', 'run_sql', 'search_policy']
> 21 of 21 checks passed.
> ...
> ALL CHECKS PASSED
>
> ALL PARTS PASS. The agents are worth scoring.
> ```

| Part | What it checks |
|---|---|
| The database | The answers the golden questions depend on, and the two traps in the raw tables |
| The SQL guardrail | Only one read-only `SELECT`, only on the tables the mode allows |
| Policy search | The right passage comes first, including by a synonym ("money back" finds the refund rules) |
| The MCP server | It starts, and offers the same three tools in both modes, described differently |
| The ontology | The Day 4 checks, still passing on the data the database is built from |

### 10. Compare the two shapes, and try the guardrail

What the raw agent is told about the data:

```bash
python3 -c "from northwind import sql; import json; print(json.dumps(sql.describe('raw'), indent=1))" | head -20
```

> **Expected:** table names and bare column names, nothing else:
> `cust_tbl: cref, nm, vf, circ`, `acc_tbl: aref, eml, cref, vuln`, and so on. Two columns
> sound like vulnerability (`vf` and `vuln`). Nothing says which one to trust.

What the semantic agent is told:

```bash
python3 -c "from northwind import sql; import json; print(json.dumps(sql.describe('semantic'), indent=1))" | head -30
```

> **Expected:** four views, each with a description and every column explained, for
> example `condition_grade: A (as new), B (opened, working) or C (damaged or faulty)`.

A policy search, exactly as the agent would run it:

```bash
python3 -c "from northwind import policy_search as p; r = p.search('Can we give compensation for a late delivery?')['passages'][0]; print(r['source']); print(r['text'])"
```

> **Expected:**
> ```
> delivery_delays.md#Goodwill credit for long delays
> There is no automatic compensation for late delivery. For a delivery more than 5 days
> late, the complaints team lead may approve a goodwill credit of up to 5 pounds, ...
> ```

And the guardrail, stopping two unsafe queries:

```bash
python3 -c "from northwind import sql; print(sql.run('DELETE FROM rtn_tbl', 'raw')); print(sql.run('SELECT * FROM returns_v', 'raw'))"
```

> **Expected:**
> ```
> {'status': 'blocked', 'reason': 'Only SELECT queries are allowed.'}
> {'status': 'blocked', 'reason': 'Not allowed in raw mode: returns_v. Allowed: acc_tbl, ...'}
> ```

---

## Run the three agents

### 11. Start the chat server

```bash
source ~/adk-env/bin/activate
cd "$KIT/agents"
adk web
```

> **Expected:** `Uvicorn running on http://127.0.0.1:8000`

Leave this terminal alone. When you first talk to a grounded agent, ADK starts the MCP
server for it, and you see lines such as `Processing request of type ListToolsRequest`
and `CallToolRequest`. Those are the agent and the server talking.

### 12. Ask all three agents the same questions

In the browser, go to **http://127.0.0.1:8000**. For each question, ask each of the three
agents, clicking **New Session** every time. Watch the reply and the tool boxes: a
grounded agent shows `describe_data`, `run_sql` or `search_policy`, and you can click a box
to see the SQL it wrote or the passage it found.

```
How many complaints come from customers who are vulnerable?
```
> **Expected:** `v6_ungrounded` cannot know. `v6_grounded_semantic` usually answers **two,
> C-103 and C-105**, from `customer_is_vulnerable`. `v6_grounded_raw` may get it wrong: two
> columns sound right, and the one on the accounts table (`vuln`) is a legacy flag that
> disagrees with the customer. Click its `run_sql` box to see which it used.

```
How many returned items are grade C?
```
> **Expected:** the semantic agent answers **3**. The raw agent finds `grd`, which holds
> codes 1 to 3 with nothing to say that 3 means C. It may answer 0, or guess the code
> correctly. Either way, compare its SQL with the semantic agent's.

```
Can we give a customer compensation for a delivery that was five days late?
```
> **Expected:** both grounded agents call `search_policy` and cite the **delivery delay
> policy**: no automatic compensation; for more than 5 days late, the team lead may approve
> a goodwill credit of up to 5 pounds. The ungrounded agent cannot cite anything.

```
The customer on complaint C-106 wants a full refund. Can the complaints service pay it without approval?
```
> **Expected:** a grounded agent uses **both** tools: `run_sql` finds the order is worth 35
> pounds, and `search_policy` finds that above 25 pounds the Billing team lead must approve.
> So the answer is no.

Record what you saw on the **Run it** page of the worksheet.

---

## Measure the before and after

### 13. Run all ten golden questions on all three agents

This does not need the chat server. It calls the model 30 times, takes a few minutes and
costs a few pence.

```bash
cd "$KIT"
cat eval/grounding_questions.yaml
python3 eval/run_grounding.py
```

> **Expected:** one line per question, one column per agent, then totals.
> ```
> 10 questions x 3 agents, on gemini-2.5-flash
>
>   #    needs   ungrounded              raw                     semantic
>   G1   sql     FAIL context      460 tok  FAIL reasoning  2,156 tok  PASS            3,783 tok
>   G2   sql     FAIL context      460 tok  PASS              990 tok  PASS              995 tok
>   ...
>
>   Totals
>     ungrounded    0 of 10 correct    ...
>     raw           7 of 10 correct    ...
>     semantic     10 of 10 correct    ...
>
>   Fixed by the semantic layer: G1, G4, G5
>
>   Results written to baseline/grounding_v1.json
> ```
> Your numbers will differ: that example is only the shape. What matters is the pattern:
> ungrounded scores lowest, and the questions where raw and semantic differ are the ones
> where the shape of the data matters.

| In the output | Meaning |
|---|---|
| `PASS` / `FAIL` | Whether the answer contains the expected facts |
| `FAIL context` | The answer was never in front of the model: no tool, or empty rows |
| `FAIL tool` | A tool failed or was blocked, and the agent did not recover |
| `FAIL reasoning` | The right data came back, and the answer was still wrong |
| `tok` | Tokens the model read and wrote for that answer. Compare raw with semantic |
| Fixed by the semantic layer | Questions raw got wrong and semantic got right: the proof |

The cause is a **first guess** from what the tools returned. Confirming or correcting it is
your job in the next step.

### 14. Diagnose three failures

Look at the answers and the tool calls behind them:

```bash
python3 -m json.tool baseline/grounding_v1.json | less
```

Re-run one question on one agent to watch it closely:

```bash
python3 eval/run_grounding.py raw G4
```

For three failures, decide the cause, and what would fix it:

| Cause | Typical fix |
|---|---|
| Context | Better data: a clearer view, a missing column, a policy that says it |
| Tool | A better tool: clearer description, a better error message, a new tool |
| Reasoning | A better instruction, or move the decision into code |

### 15. Context budget, ADR-6 and the seven questions

Set a **context budget** per answer, in tokens, using the token column. Then write ADR-6:
which grounding pattern you would use, and why. Answer the seven questions in
`usecase1_day6.pdf`.

Do not change the data, views or policies during the exercise. Proposals go in ADR-6.

---

## Optional: BigQuery and Vertex AI RAG

The default route needs nothing but the VM. These options move the same data and policies
into Google Cloud, with no change to the agents. They need extra libraries and permissions
in your project, so try them only after the rest works.

**BigQuery instead of SQLite.** Load the tables and views once, into a dataset named
after your VM user so learners sharing a project do not overwrite each other, then switch:

```bash
pip install google-cloud-bigquery
export BQ_DATASET="<YOUR_PROJECT_ID>.northwind_day6_${USER}"
cd "$KIT"
python3 -c "from northwind import sql; sql.bigquery_setup()"
export SQL_BACKEND=bigquery
```

**Vertex AI RAG Engine instead of local search.** Upload the policies once, then switch:

```bash
pip install google-cloud-aiplatform
export GOOGLE_CLOUD_PROJECT="<YOUR_PROJECT_ID>"
cd "$KIT"
python3 -c "from northwind import policy_search as p; p.vertex_setup()"
```

> **Expected:** six `uploaded ...` lines, then an `export VERTEX_RAG_CORPUS=...` line. Run
> that line, then `export RAG_BACKEND=vertex`.

Start `adk web` again in the **same terminal**, so the agents and their MCP server see these
settings. To go back to the defaults: `unset SQL_BACKEND RAG_BACKEND`.

---

## Stop the chat server

**Normally:** press **Ctrl + C** in the terminal running `adk web`. The MCP servers it
started stop with it.

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

Still busy on port 8000? Start on another port instead: `adk web --port 8001`.

**Clear the saved chat sessions too**, so an old conversation does not reappear:

```bash
rm -rf "$KIT"/agents/*/.adk
```

**To come back later:**

```bash
source ~/adk-env/bin/activate
cd "$KIT/agents"
adk web
```

---

## If something breaks

Put your hand up first. Do not spend the session fixing the environment.

| Symptom | Likely cause | Fix |
|---|---|---|
| `No such file or directory` for `usecase1/usecase01_day6` or `setup.sh` | Repository not updated, or `~/domainFDE` is not a clone of GitHub | `cd ~/domainFDE && git pull`; if still missing, step 5c (fresh clone) |
| `git pull` prints `not a git repository`, `would be overwritten` or `diverged` | The folder was unzipped, copied or edited | Step 5c: move it aside and clone again |
| `$KIT` points to the wrong folder, such as an earlier day | An older `export KIT` line is used | Repeat the `echo` line in step 5b, then `source ~/.bashrc` and `echo $KIT` |
| `ModuleNotFoundError: No module named 'mcp'` | ADK's MCP support is not installed | Step 6b: `pip install "google-adk[mcp]"` |
| `No module named 'mcp.server.fastmcp'`, or a message about `MCPServer` | `mcp` version 2 is installed | `pip install "mcp>=1.24,<2"` |
| `pip` warns that `google-adk requires opentelemetry-api ...` | Something upgraded a library ADK depends on | `pip install "google-adk[mcp]"` again, to restore it |
| `ModuleNotFoundError: No module named 'yaml'`, `'google'` or `'northwind'` | ADK environment not active, or not run from `$KIT` | `source ~/adk-env/bin/activate`, `cd "$KIT"`, then run it again |
| `adk: command not found` | Environment not active in this terminal | `source ~/adk-env/bin/activate` |
| Empty drop-down, or only some agents listed | Server started from the wrong folder | `Ctrl + C`, `cd "$KIT/agents"`, start again |
| A grounded agent hangs, or says it cannot reach its tools | The MCP server failed to start | Stop `adk web`, run `bash tests/check_parts.sh`; Part 4 shows whether the server starts |
| A tool box shows `"status": "blocked"` | The SQL guardrail stopped a query | Working as intended. The agent should rewrite the query |
| `PERMISSION_DENIED` / `403` in the reply | Identity cannot call Vertex AI | `bash "$KIT/setup.sh"` and follow what it prints |
| `SERVICE_DISABLED` | Vertex AI API is off | Step 4 |
| `A PART FAILED` in step 9 | A file was changed | `cd "$KIT" && git checkout -- .` |
| Port 8000 already in use | Old chat server still running | `pkill -f "bin/adk"`, or `adk web --port 8001`. See "Stop the chat server" |
| Different results on a second run | Normal; models vary | Record both. It is a worksheet question |

---

## How the Day 6 agents differ from Day 5

The Day 5 and Day 6 agents are built for **different jobs**. Neither is simply better: one
acts on a case, the other answers questions from the company's records and policies.

| | Day 5 agents | Day 6 agents |
|---|---|---|
| **Job** | **Act** on one case: apologise, refund, decide where a return goes | **Answer questions** about many records and about policy |
| **Tools** | Look up one complaint or return by ID, then act (send, refund, set disposition, claim) | Describe the data, run a read-only SQL query, search the policies |
| **Can change things?** | Yes, within the guardrail | No, read only |
| **Knows policy?** | Only what is written in its instruction | Reads the actual policy documents, and cites them |
| **Sees many records at once?** | No, one ID at a time | Yes, any question SQL can answer |

**The same prompts, on both.** Ask these to `v5a_loop_agent` in the Day 5 kit, and to
`v6_grounded_semantic` here:

| Prompt | Day 5 (`v5a_loop_agent`) | Day 6 (`v6_grounded_semantic`) |
|---|---|---|
| "Send C-104 an apology by email." | Looks it up and **sends it** | Cannot send anything; it can only say what the records show about C-104 |
| "How many returned items are grade C?" | Cannot answer: it looks up one ID at a time | **"3"**, from `returns_v` |
| "What does grade C mean?" | Answers from the model's general knowledge, or says it does not know | **"Damaged or faulty; never restocked"**, citing `returns_grading.md` |
| "Can we give compensation for a five-day delay?" | **"No, there is no compensation policy"** | **"No automatic compensation; for delays over 5 days the team lead may approve a goodwill credit up to 5 pounds"**, citing `delivery_delays.md` |

**The last row is the lesson of the day.** The Day 5 instruction says, word for word,
*"Never offer a discount, voucher or compensation. No such policy exists."* That sentence was
written into the prompt by hand, when the agent had no way to check. The delivery delay
policy says a goodwill credit **does** exist, approved by the team lead.

- **The rule still agrees:** the agent itself may never offer the credit, and the policy
  says the same.
- **The fact does not:** the Day 5 agent confidently tells staff something that is not true.

A fact hard-coded into an instruction goes stale. A grounded agent reads the current source,
and shows you where it came from. Keep this example for the debrief.
