# Day 5 · Use case 1: one agent becomes a team

The complaints desk keeps receiving cases that are not only complaints. A cracked kettle is
a complaint, a **return** that needs a decision about where the item goes, and a **refund**.
Today the single complaints agent becomes **three specialists** (complaints, returns and
billing), each with its own three tools and its own rules, put to work in **four
patterns**:

| # | Agent | Pattern | Next step decided by |
|---|---|---|---|
| A | `v5a_loop_agent` | Agent loop, Agent approach | The model |
| B | `v5b_loop_graph` | Agent loop, Graph API approach | Code, drawn as a graph |
| C | `v5c_router_graph` | Router, Graph API approach | Code first, the model only when unsure |
| D | `v5d_orchestrator` | Orchestrator, multi-agent | The model, calling specialists as tools |

You will look inside each pattern, try each one in the chat, run a small eval set, and
decide which pattern you would ship first.

Read in this order:

1. `usecase1_day5_problem_statement.pdf`: the business case. Three teams, and how one customer
   problem crosses customer experience, supply chain and finance.
2. `usecase1_day5.pdf`: the practical. What was built, the four patterns, your task and the
   seven questions.
3. `ARCHITECTURE.md`, when you want to know how the pieces fit together.

Record everything in `Day5_Worksheets_UC01.docx`.

Fill in `<YOUR_GOOGLE_ACCOUNT>` and `<YOUR_PROJECT_ID>` wherever they appear. Everything
else pastes as written. You work in a terminal on **your VM**; the browser is the one
on the VM too. Using the shared training account? Follow `README-training-account.md`
instead: it is this page, pre-filled.

The code lives in this repository under `usecase01_day5/Agentimplementation/`. The
commands below set one variable, `$KIT`, pointing at that folder, and use it everywhere.

---

## Setup: first time only

If you completed setup on this VM for an earlier day, with the same account and project,
steps 1 to 4 and 6 are already done. Do steps 5 and 7, then carry on at step 8.

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

Already cloned for an earlier day? Update it, so you get the Day 5 folder:

```bash
cd ~/domainFDE
git pull
```

**5b. Set the variable every command below relies on**, and make it stick for new
terminals:

```bash
echo 'export KIT="$HOME/domainFDE/usecase01_day5/Agentimplementation"' >> ~/.bashrc
source ~/.bashrc
echo $KIT
ls "$KIT/setup.sh"
ls "$KIT/agents"
```

> **Expected:**
> ```
> /home/<you>/domainFDE/usecase01_day5/Agentimplementation
> /home/<you>/domainFDE/usecase01_day5/Agentimplementation/setup.sh
> v5a_loop_agent  v5b_loop_graph  v5c_router_graph  v5d_orchestrator
> ```

**5c. Only if `ls "$KIT/setup.sh"` says `No such file or directory`.** Your
`~/domainFDE` folder does not match GitHub. Usually it was unzipped or copied rather
than cloned, it came from somewhere else, or `git pull` stopped on local files. Check:

```bash
cd ~/domainFDE
git remote -v
git log -1 --format='%h %cd %s'
ls ~/domainFDE/usecase01_day5
```

> **Healthy:** the remote is `https://github.com/Bluedata-Consulting/DomainFDE.git`, and
> `ls` shows `Agentimplementation`, both READMEs, `ARCHITECTURE.md`,
> `usecase1_day5_problem_statement.pdf`, `usecase1_day5.pdf` and the worksheet.

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

### 7. Run the setup check

```bash
bash "$KIT/setup.sh"
```

It writes `usecase01_day5/Agentimplementation/agents/.env` (your project, region and
model) and makes one real call to the model, so any access problem shows up here rather
than in the exercise.

> **Expected:** `Model access ... OK` and `Setup finished.`

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

## Check the parts and meet the agents (no model)

Fill in the prediction page of the worksheet **before** this part.

### 8. Run every component test

```bash
source ~/adk-env/bin/activate
cd "$KIT"
bash tests/check_parts.sh
```

> **Expected:** three blocks, then the verdict.
> ```
> Part 1: the rules, one team at a time
>   PASS  C1 Complaint from a vulnerable customer (C-105)  ...
>   PASS  R1 Restock the recalled heater (R-202)           ...
> Part 2: the code router
>   PASS  A return ID goes to returns                        ...
> 16 of 16 checks passed.
> ...
> 5 of 5 metrics matched.
> ...
> ALL CHECKS PASSED
>
> ALL PARTS PASS. The agent is worth scoring.
> ```

| Part | Test | From |
|---|---|---|
| Every team's rules, and the code router | `tests/test_rules.py` | Days 2 and 5 |
| The metrics and their budgets | `tests/test_metrics.py` | Day 3 |
| The ontology and the data | `tests/test_ontology.py` | Day 4 |

### 9. Look inside each pattern

`show_context.py` prints how each agent is built. No model is called.

```bash
python3 show_context.py v5a_loop_agent
```

> **Expected:** the complaints instruction, then three tools: `get_complaint`,
> `send_customer_message` and `escalate_to_human`. There is no refund tool: refunds belong
> to Billing now.

```bash
python3 show_context.py v5b_loop_graph
```

> **Expected:** a graph. Every node is marked `code` or `model`, and every route is shown:
> ```
>   node  prepare              code
>   node  reply_drafter        model
>   node  check                code
>   node  send                 code
>   ...
>   reply_drafter        ------->          check
>   check                --retry-->        reply_drafter
>   check                --send-->         send
>   check                --person-->       person
> ```
> The model only writes the words. Code decides whether they go out.

```bash
python3 show_context.py v5c_router_graph
```

> **Expected:** `route_by_rules` (code) routes to `complaints_agent`, `returns_agent` or
> `billing_agent`, or to `route_classifier` (model) when it is `unsure`.

```bash
python3 show_context.py v5d_orchestrator
```

> **Expected:** the coordinator's three tools are the three specialists, each listing its
> own three tools.

---

## Run the four patterns

### 10. Start the chat server

```bash
source ~/adk-env/bin/activate
cd "$KIT/agents"
adk web
```

> **Expected:** `Uvicorn running on http://127.0.0.1:8000`

Leave this terminal alone. Watch it next to the browser:

| Terminal line | Meaning |
|---|---|
| `>>> ROUTED BY CODE` / `>>> ROUTED BY MODEL` | Which team the router chose, and what decided |
| `>>> ACTION TAKEN BY AGENT` | A rule allowed the action, and it ran |
| `>>> BLOCKED BY GUARDRAIL` | A rule stopped the action. It did not run |
| `>>> ESCALATED TO HUMAN` | A named person now has it |

### 11. Try each pattern

In the browser, go to **http://127.0.0.1:8000**. Choose the agent from the drop-down, click
**New Session** before every prompt, and watch the reply, the tool boxes and the terminal.
The model's wording varies; the `>>>` lines are what to compare.

**Pattern A · `v5a_loop_agent`: the model runs the loop**

```
Send the customer on complaint C-104 a short apology by email about the wrong lamp colour.
```
> **Expected:** the agent looks the complaint up, then `ACTION TAKEN BY AGENT:
> send_customer_message | C-104 via email (service)`. You did not tell it which tools to
> call, or in what order: it decided.

```
Refund the customer on complaint C-102 40 pounds.
```
> **Expected:** nothing is refunded, and there is no `>>>` line for a refund. The complaints
> agent has no refund tool, so it says that Billing decides refunds. The boundary is in the
> tool list, not in a rule.

**Pattern B · `v5b_loop_graph`: the graph runs the loop**

```
Write and send the customer on C-104 an apology by email.
```
> **Expected:** `reply_drafter` writes a draft, `check` tests it in code, and it is sent:
> `ACTION TAKEN BY AGENT: send_customer_message | C-104 via email (service)`. The reply says
> how many drafts it took. If the first draft offered anything, you see a second draft.

```
Write and send the customer on C-105 an apology by email.
```
> **Expected:** `ESCALATED TO HUMAN: C-105 -> Complaints team lead`, and no draft at all.
> `prepare` stopped it in code before the model was ever asked.

```
Write and send the customer on C-102 an apology by phone.
```
> **Expected:** a draft is written, then `check` finds no consent for service calls by
> phone, and hands it to the team lead. Nothing is sent. This is the Day 4 consent
> contradiction, now stopping a graph.

**Pattern C · `v5c_router_graph`: one entry point, routed**

```
What should happen to return R-202?
```
> **Expected:** `ROUTED BY CODE: returns | It names a return (R-...)`. The returns
> specialist finds a recalled space heater. It quarantines it, or tries to restock it and
> gets `BLOCKED ... RECALLED` with an escalation to the **Returns supervisor**.

```
Complaint C-102: I want my money back for the 40 pound overcharge.
```
> **Expected:** `ROUTED BY CODE: billing | It asks for money back`. The billing specialist
> cannot refund 40 pounds on its own: `NEEDS_APPROVAL`, or it asks the **Billing team lead**
> for approval straight away.

```
Nobody is helping me with my order and I am fed up.
```
> **Expected:** `ROUTED BY CODE: unsure`, then `ROUTED BY MODEL: ...`. No ID and no money
> words, so the model decides. It usually picks complaints, or asks you for an ID.

```
Complaint C-106: the kettle is cracked, the customer wants their money back, and it came back as return R-206.
```
> **Expected:** `ROUTED BY CODE: unsure | The request touches more than one team`, then the
> model says `several`, and the request is handed to a person. A router sends each request
> to **one** team, so this is the right behaviour. Pattern D is built for it.

**Pattern D · `v5d_orchestrator`: several specialists, one answer**

```
Complaint C-106: the kettle is cracked, the customer wants their money back, and it came back as return R-206. Sort it all out.
```
> **Expected:** the tool boxes show the coordinator calling `billing_agent`, `returns_agent`
> and `complaints_agent`. In the terminal, usually:
> - Billing: 35 pounds is above the limit, so `BLOCKED ... NEEDS_APPROVAL` and/or an
>   approval request to the **Billing team lead**
> - Returns: `ACTION TAKEN BY AGENT: set_disposition | R-206 -> return_to_vendor` and a
>   `raise_vendor_claim`, because the kettle is grade C and Brewline's deadline is open
> - Complaints: an apology to Aisha by chat or email
>
> Then one combined answer.

```
Decide what happens to return R-203, the laptop.
```
> **Expected:** only `returns_agent` is called. A 1,400 pound laptop is **high value**: any
> decision is `BLOCKED ... HIGH_VALUE` and escalated to the Returns supervisor. The
> coordinator cannot get round that, because the rule lives inside the specialist.

Record what you saw on the **Run it** page of the worksheet.

---

## Score the patterns

### 12. Run the eval set

Seven cases, one or two per pattern. Each runs in a fresh session. This does not need the
chat server, but it does call the model, so it takes a few minutes and costs a few pence.

```bash
cd "$KIT"
cat eval/cases.yaml
python3 eval/run_eval.py
```

> **Expected:** a line per case, then totals by kind and by pattern.
> ```
> Running 7 cases on gemini-2.5-flash
>
>   #   Agent             Kind            Path  State  Answer  Forbidden ran   Result
>   A1  v5a_loop_agent    should_usually  1.00  ok     1.00    none            PASS
>   A2  v5a_loop_agent    must_never      1.00  ok     1.00    none            PASS
>   B1  v5b_loop_graph    should_usually  1.00  ok     1.00    none            PASS
>   ...
>   Must never     3 of 3 passed
>   Should usually 3 of 4 passed
>     A loop agent    2 of 2
>     B loop graph    2 of 2
>     C router        2 of 2
>     D orchestrator  0 of 1
>
>   Baseline written to baseline/baseline_v1.json
> ```

| Column | Meaning |
|---|---|
| Path | How many of the expected steps appeared: tools, specialists, or `escalated` |
| State | Whether the run left the right facts behind, such as `route_source: code` or `sent: true` |
| Answer | How many of the expected words appear in the final answer |
| Forbidden ran | A tool that must never run in this case, and did. Any entry is a failure |

Your numbers will differ. What matters is the shape: **must-never cases should pass**,
because code enforces them, and the orchestrator is the case most likely to vary, because
the model plans it.

### 13. Look at one failure, and classify it

```bash
python3 eval/run_eval.py D1 --no-save
python3 -m json.tool baseline/baseline_v1.json | head -30
```

For every failure, decide which of four things is wrong:

| Cause | What it looks like | What you do about it |
|---|---|---|
| The model | The rules allowed it; the agent chose badly | Instruction, tool description, or make it code |
| The rules | Something got through that should have been stopped | A new rule: ADR-5 |
| The expected answer | The agent was right and the case was wrong | Change the case, with the owner's agreement |
| The harness | A different but acceptable path scored low | Loosen the metric, not the behaviour |

### 14. ADR-5 and the seven questions

Choose the pattern you would ship first, draw it on the architecture page of the worksheet,
and write ADR-5. Then answer the seven questions in `usecase1_day5.pdf`.

Do not change the agents, the cases or the thresholds during the exercise. Proposals go in
ADR-5.

---

## Stop the chat server

**Normally:** press **Ctrl + C** in the terminal running `adk web`.

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

Still busy on port 8000? Start on another port instead: `adk web --port 8001`.

**Clear the saved chat sessions too**, so an old conversation does not reappear next time:

```bash
rm -rf "$KIT"/agents/*/.adk
```

**To come back later:**

```bash
source ~/adk-env/bin/activate
cd "$KIT/agents"
adk web
```

Refunds, dispositions and claims made by the agents are kept in memory while the server
runs. Restarting resets them to what `data/northwind.json` says.

---

## If something breaks

Put your hand up first. Do not spend the session fixing the environment.

| Symptom | Likely cause | Fix |
|---|---|---|
| `No such file or directory` for `usecase01_day5` or `setup.sh` | Repository not updated, or `~/domainFDE` is not a clone of GitHub | `cd ~/domainFDE && git pull`; if still missing, step 5c (fresh clone) |
| `git pull` prints `not a git repository`, `would be overwritten` or `diverged` | The folder was unzipped, copied or edited | Step 5c: move it aside and clone again |
| `$KIT` points to the wrong folder | An older `export KIT` line is used | Repeat the `echo` line in step 5b, then `source ~/.bashrc` and `echo $KIT` |
| `ModuleNotFoundError: No module named 'yaml'`, `'google'` or `'northwind'` | ADK environment not active, or not run from `$KIT` | `source ~/adk-env/bin/activate`, `cd "$KIT"`, then run it again |
| `adk: command not found` | Environment not active in this terminal | `source ~/adk-env/bin/activate` |
| Empty drop-down, or only some agents listed | Server started from the wrong folder | `Ctrl + C`, `cd "$KIT/agents"`, start again |
| `A PART FAILED` in step 8 | A file was changed | `cd "$KIT" && git checkout -- .` |
| `PERMISSION_DENIED` / `403` in the reply | Identity cannot call Vertex AI | `bash "$KIT/setup.sh"` and follow what it prints |
| `SERVICE_DISABLED` | Vertex AI API is off | Step 4 |
| A graph agent shows no reply text | The graph ended on a node that only saves state | Check the terminal for `>>>` lines; they show where it stopped |
| The orchestrator calls only one specialist | Normal: it plans each request itself | Record it. It is what D1 in the eval set measures |
| The eval run stops partway | A model call failed or timed out | Run one case: `python3 eval/run_eval.py A1 --no-save` |
| Port 8000 already in use | Old chat server still running | `pkill -f "bin/adk"`, or `adk web --port 8001`. See "Stop the chat server" |
| Different results on a second run | Normal; models vary | Record both. It is a worksheet question |
