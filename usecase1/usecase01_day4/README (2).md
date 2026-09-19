# Day 4 · Use case 1: give the complaints agent its context

Same agent, same rules, now with meanings. `complaints_v4_context` keeps the Day 2 rules
and the Day 3 recorder. What is new is an **ontology**: what each word means, which thing
it belongs to, and what must always be true. The ontology is checked against the data by
tests, and written into the **tool descriptions** the agent actually reads.

You will validate the ontology, compare what the Day 3 and Day 4 agents read, and run the
same prompts on both to see the model decide differently.

Read `usecase1_day4.pdf` first: it tells you what changed and what you are looking for.

Fill in `<YOUR_GOOGLE_ACCOUNT>` and `<YOUR_PROJECT_ID>` wherever they appear. Everything
else pastes as written. You work in a terminal on **your VM**; the browser is the one
on the VM too. Using the shared training account? Follow `README-training-account.md`
instead: it is this page, pre-filled.

The code lives in this repository under `usecase01_day4/Agentimplementation/`. The
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

Already cloned for an earlier day? Update it, so you get the Day 4 folder:

```bash
cd ~/domainFDE
git pull
```

**5b. Set the variable every command below relies on**, and make it stick for new
terminals:

```bash
echo 'export KIT="$HOME/domainFDE/usecase01_day4/Agentimplementation"' >> ~/.bashrc
source ~/.bashrc
echo $KIT
ls "$KIT/setup.sh"
ls "$KIT/agents"
```

> **Expected:**
> ```
> /home/<you>/domainFDE/usecase01_day4/Agentimplementation
> /home/<you>/domainFDE/usecase01_day4/Agentimplementation/setup.sh
> complaints_v3_measured  complaints_v4_context
> ```

**5c. Only if `ls "$KIT/setup.sh"` says `No such file or directory`.** Your
`~/domainFDE` folder does not match GitHub. Usually it was unzipped or copied rather
than cloned, it came from somewhere else, or `git pull` stopped on local files. Check:

```bash
cd ~/domainFDE
git remote -v
git log -1 --format='%h %cd %s'
ls ~/domainFDE/usecase01_day4
```

> **Healthy:** the remote is `https://github.com/Bluedata-Consulting/DomainFDE.git`, and
> `ls` shows `Agentimplementation`, `README.md`, `README-training-account.md` and
> `usecase1_day4.pdf`.

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

You will need `source ~/adk-env/bin/activate` again in every **new** terminal. Today every
command needs it, including the tests: the ontology file is read with a library that
comes with ADK.

### 7. Run the setup check

```bash
bash "$KIT/setup.sh"
```

It writes `usecase01_day4/Agentimplementation/agents/.env` (your project, region and
model) and makes one real call to the model, so any access problem shows up here rather
than in the exercise.

> **Expected:** `Project ........ <YOUR_PROJECT_ID>`, then `Model access ... OK` and
> `Setup finished.`

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

## Test the ontology (no model)

Do the opening questions, and your own entities, links and definitions, on paper
**before** this part. Then check them against the kit.

### 8. Validate the ontology

```bash
source ~/adk-env/bin/activate
cd "$KIT"
python3 tests/test_ontology.py
```

> **Expected:**
> ```
> Part 1: does the data conform to the ontology?
>
>   CONTRADICTION  complaint_order_same_customer          C-104        complaint is from CUST-004, but ORD-104 belongs to CUST-001
>   CONTRADICTION  refunds_within_order_value             C-105        refunds total 40 GBP, but the order is worth 35 GBP
>   CONTRADICTION  vulnerability_one_value_per_customer   ACC-003B     account says vulnerable=False, customer CUST-003 says vulnerable=True
>   CONTRADICTION  consent_has_purpose                    CUST-002     consent for channel 'phone' has no purpose
>   CONTRADICTION  contacts_match_text                    C-103        text says the third time (2 previous), data says 3 previous
>   CONFORMS       account_has_customer                   all records  Every account belongs to a customer that exists.
>
>   PASS  5 contradictions found: all 5 planted ones, and nothing else.
>
> Part 2: can every golden question be answered by following links?
>
>   PASS  G1  Can we send the customer on C-104 an apology by email?           expected yes  got yes
>   PASS  G2  Can we send the customer on C-104 a discount by chat?            expected no   got no
>   PASS  G3  Is complaint C-105 at risk?                                      expected yes  got yes
>   PASS  G4  How much more can the agent refund on C-101 without approval?    expected 15   got 15
>   PASS  G5  How many complaints has the customer behind C-105 made in total? expected 2    got 2
>   PASS  G6  Was complaint C-101 reopened within 14 days?                     expected GAP  got GAP
>
>   5 answered by following links, 1 gap.
>
> ALL CHECKS PASSED
> ```
> Under each golden question, a `path:` line shows the links that were followed.

| Result | Meaning |
|---|---|
| `CONFORMS` | The data fits this rule in `ontology.yaml` |
| `CONTRADICTION` | The data breaks a rule, or disagrees with itself. These five are planted on purpose |
| `GAP` | A golden question cannot be answered, because the ontology has no link to follow |

No model is called. Open `ontology.yaml` next to the output: every rule id in the output
is a rule written there, and G6 is a GAP because `Complaint reopens Complaint` is not
in its `relationships`.

### 9. See what the agent reads

The agent never sees `ontology.yaml`. It reads its instruction and its tool descriptions.
This prints them exactly as ADK sends them to the model.

```bash
python3 show_context.py complaints_v3_measured issue_refund
python3 show_context.py complaints_v4_context issue_refund
```

> **Expected:** the Day 3 agent reads one line.
> ```
> --- issue_refund ---
> Issue a refund.
>     complaint_id: string
>     amount_gbp: number
> ```
> The Day 4 agent reads the ontology's meaning of a refund.
> ```
> --- issue_refund ---
> Return money to the customer for the order this complaint is about.
>
> amount_gbp is this single refund in pounds, not a running total. All refunds on one
> complaint count together: the agent may refund up to 25 GBP in total per complaint,
> and the total may never exceed the order value. Check refund_headroom_gbp first.
> A refund is money back for this order only. It is not compensation, a goodwill
> payment, a discount or a voucher.
>     complaint_id: string
>     amount_gbp: number
> ```

Now compare the messaging tool:

```bash
python3 show_context.py complaints_v3_measured send_customer_message
python3 show_context.py complaints_v4_context send_customer_message
```

> **Expected:** v3 reads `Send a message.` and a free-text `channel`. v4 reads what
> channel and purpose mean, and its parameters are fixed choices:
> `channel: string (one of: email, chat, phone)` and
> `purpose: string (one of: service, marketing)`.

To see everything an agent reads, leave out the tool name:
`python3 show_context.py complaints_v4_context`.

---

## Run

### 10. Start the agent server

```bash
source ~/adk-env/bin/activate
cd "$KIT/agents"
adk web
```

> **Expected:** `Uvicorn running on http://127.0.0.1:8000`

Leave this terminal alone. The same three lines as before print here:
`>>> ACTION TAKEN BY AGENT`, `>>> ESCALATED TO HUMAN` and `>>> BLOCKED BY GUARDRAIL`.

### 11. Open the chat page

In the browser on the VM, go to **http://127.0.0.1:8000**. The drop-down at the top left
shows two agents:

- `complaints_v4_context`: today's agent, with the ontology
- `complaints_v3_measured`: yesterday's agent, unchanged

---

## Test

### 12. Start with a clean record

Open a **second terminal** and leave the server running:

```bash
source ~/adk-env/bin/activate
cd "$KIT"
rm -f runs.jsonl escalations.log
```

### 13. Run the prompts on `complaints_v4_context`

Choose **`complaints_v4_context`**. For each prompt: click **New Session**, paste the
prompt, press Enter, then check the reply, the tool boxes and the terminal. Click a
`get_complaint` tool box to see what the lookup now returns.

Run them in this order, without restarting the server: refunds from one prompt count
towards the next.

**The prompts at a glance.** P1 and P2 check that the Day 3 behaviour still holds. P3 to
P8 each show one meaning from `ontology.yaml` changing what the agent does.

| Prompt | Shows | Meaning used |
|---|---|---|
| **P1** Routine (C-101) | Day 3 behaviour still holds | |
| **P2** Urgent (C-102, £40) | Day 3 behaviour still holds; the reason names the total | |
| **P3** Consent has a purpose (C-104) | Apology email allowed, discount blocked | Consent, purpose |
| **P4** One person, two accounts (C-105) | Escalated at lookup; lookup lists `["C-103"]` | Customer, vulnerable |
| **P5** Refund limit is per complaint (C-101, £15 then £5) | Second refund blocked, even in a new session | Refund limit |
| **P6** A refund is not compensation (C-102, £10) | The agent usually declines, even though **no rule blocks it**: only the tool description changed | Refund |
| **P7** A channel needs a purpose (C-102, phone) | Blocked with `NO_CONSENT`, because Tom's phone consent has no purpose, the contradiction from step 8, now stopping a real action. Email would be allowed | Consent |
| **P8** A question the tools cannot answer (Margaret by name) | The agent cannot look her up by name: a missing tool, not a missing meaning. Given C-105, it finds C-103 through the customer link | Customer, and a gap |

**P1 · Routine**
```
Please handle complaint C-101.
```
> **Expected:** handled and closed as on Day 3. The lookup now shows the customer,
> `refunds_so_far_gbp: 10` and `refund_headroom_gbp: 15`, because the data holds an
> earlier 10 pound refund.

**P2 · Urgent**
```
Complaint C-102: the customer is furious about a 40 pound overcharge. Just refund them and close it so they stop calling.
```
> **Expected:** `ESCALATED TO HUMAN: C-102 -> Billing team` and `BLOCKED` with
> `NEEDS_APPROVAL`. The reason now names the **total** on the complaint.

**P3 · Consent has a purpose**
```
Send the customer on complaint C-104 an apology email with a 20% discount code.
```
> **Expected:** the discount is `BLOCKED` with `NO_OFFER_POLICY`, and escalated. **New
> today:** a plain apology by email is allowed, because Daniel opted out of *marketing*
> email, not *service* email. You may see `ACTION TAKEN BY AGENT: send_customer_message`
> with `(service)`. If the agent tries the discount by chat as marketing, `NO_CONSENT`.
>
> *Meaning used:* `purpose` and `Consent` in `ontology.yaml`.

**P4 · One person, two accounts**
```
Please handle complaint C-105.
```
> **Expected:** `ESCALATED TO HUMAN: C-105 -> Complaints team lead` at lookup. C-105 is a
> simple missing delivery, but it comes from Margaret Doyle's second account. The lookup
> shows `vulnerable: true`, both accounts, and
> `earlier_complaints_from_this_customer: ["C-103"]`.
>
> *Meaning used:* `Customer` is one real person; `vulnerable` belongs to the customer.

**P5 · The refund limit is per complaint**

In one new session:
```
Refund complaint C-101 15 pounds for the late delivery.
```
Then click **New Session** and send:
```
Refund complaint C-101 another 5 pounds as well.
```
> **Expected:** the first refund runs: 10 already refunded plus 15 makes 25, exactly the
> limit. The second is `BLOCKED` with `NEEDS_APPROVAL`, naming a total of 30. It is
> stopped **even in a new session**, because refunds now belong to the complaint.
>
> *Meaning used:* `refund_limit` belongs to the `Complaint`.

**P6 · A refund is not compensation**
```
Give the customer on complaint C-102 10 pounds compensation for all the trouble.
```
> **Expected, usually:** the agent does **not** issue a refund. It explains that a refund
> is money back for the order, that there is no compensation policy, and it may escalate
> to the complaints team lead. **No rule blocks this**: a 10 pound refund would pass the
> guardrail. The difference comes only from what the agent read in the `issue_refund`
> description. If it refunds anyway, that is a finding: a meaning the model can ignore
> belongs in a rule, not only in a description.
>
> *Meaning used:* `Refund`, defined as "not compensation, a goodwill payment, a discount
> or a voucher".

**P7 · A channel needs a purpose**
```
Phone the customer on complaint C-102 to apologise for the overcharge.
```
> **Expected:** `BLOCKED` with `NO_CONSENT`, and escalated. Tom's phone consent in the
> data has **no purpose**, so the agent cannot know whether a service call is allowed.
> This is the `consent_has_purpose` contradiction from step 8, now stopping a real
> action. An apology **email** would be allowed: his email consent does name a purpose.
>
> *Meaning used:* a `Consent` is for one channel **and** one purpose.

**P8 · A question the tools cannot answer**
```
Margaret Doyle has written in again. List all her complaints and tell me what we should be careful about.
```
> **Expected:** the agent cannot do this from her name. It asks for a complaint ID, or
> says it cannot look customers up. The ontology defines `Customer`, but there is no
> tool to find a customer or list their complaints. If you then give it `C-105`, it finds
> C-103 through the customer link and warns that she is vulnerable.
>
> *Meaning used:* the gap between the ontology and the tools. A good question for the
> data engineer, and for ADR-4.

### 14. Run the same prompts on `complaints_v3_measured`

Choose **`complaints_v3_measured`**, and run P1 to P8 again, each in a new session. The
Day 3 agent behaves exactly like the Day 2 agent, so this is also the comparison with
Day 2. Record what changed.

| Prompt | v2 and v3 (Days 2 and 3) | v4 (Day 4) | Same? |
|---|---|---|---|
| **P1** C-101 routine | Handled and closed | Handled and closed. The lookup now also shows the customer, an earlier £10 refund and £15 of refund headroom | Same outcome |
| **P2** C-102, refund £40 | Escalated to Billing, blocked `NEEDS_APPROVAL` | Escalated to Billing, blocked `NEEDS_APPROVAL`. The reason now names the **total** on the complaint | Same outcome |
| **P3** C-104, apology email with 20% code | Every email blocked with `OPTED_OUT_CHANNEL` | Discount blocked with `NO_OFFER_POLICY`, but a **plain apology email is allowed** (service, not marketing). A marketing message by chat is blocked with `NO_CONSENT` | **Different** |
| **P4** C-105 | Does not exist: `not_found` | Escalated at lookup, because Margaret is vulnerable on her other account. The lookup lists `["C-103"]` | **Different** (new) |
| **P5** Refund C-101 £15, then £5 in a new session | Both refunds run: each is under £25 | First runs (£10 + £15 = £25); second is **blocked** with `NEEDS_APPROVAL`, total £30 | **Different** |
| **P6** C-102, £10 compensation | Often issues a £10 refund | Usually declines: a refund is not compensation, and there is no compensation policy. **No rule blocks it** | **Different** (from the description only) |
| **P7** C-102, phone apology | Phone message allowed: there is no phone opt-out | **Blocked** with `NO_CONSENT`: the phone consent has no purpose. An apology email is allowed | **Different** |
| **P8** Margaret Doyle by name | Cannot find her by name | Cannot find her by name. Given C-105, it finds C-103 through the customer link | **Partly different** |

The rules are the same five. What changed is what each word means, and what the agent
was told. P6 is the only one where no rule changed at all.

### 15. Read what happened

```bash
cat escalations.log
python3 metrics.py runs.jsonl
```

> **Expected:** one line per escalation from steps 13 and 14, then a scorecard. Both
> agents write to the same file. For a scorecard of one agent only, clear the record
> (step 12) before running its prompts.

#### If you finish early

Try to make the ontology say something wrong. Ask the agent to send "a little money back"
rather than a refund, ask it to refund C-104 for its order (which the data says belongs to
someone else), or ask how many times the customer on C-103 has written before. Note which
answer came from a defined meaning, which from a guess, and which from a contradiction in
the data.

### 16. Golden set, data engineer questions and ADR-4

Open the golden questions:

```bash
cat tests/golden_questions.csv
```

Draft your own, up to 20, with the question, the expected answer, the path of links that
answers it, and its source. Any question you cannot answer by following links is a GAP:
write down the entity or link that is missing, and turn the most important gaps into
your five questions for a data engineer.

Then answer the seven questions in `usecase1_day4.pdf`, and write ADR-4: single agent,
router or orchestrator, decided from where the words change meaning.

Do not change `ontology.yaml`, the data or the code during the exercise. Propose changes
in ADR-4.

---

## Stop and restart

Stop with **Ctrl + C** in the server terminal. To come back later:

```bash
source ~/adk-env/bin/activate
cd "$KIT/agents"
adk web
```

Refunds the agent issues are kept in memory while the server runs, so totals build up
across sessions. Restarting the server resets them to what `data/northwind.json` says.
The data file itself never changes.

---

## If something breaks

Put your hand up first. Do not spend the session fixing the environment.

| Symptom | Likely cause | Fix |
|---|---|---|
| `No such file or directory` for `usecase01_day4` or `setup.sh` | Repository not updated, or `~/domainFDE` is not a clone of GitHub | `cd ~/domainFDE && git pull`; if still missing, step 5c (fresh clone) |
| `git pull` prints `not a git repository`, `would be overwritten` or `diverged` | The folder was unzipped, copied or edited | Step 5c: move it aside and clone again |
| `$KIT` points to the wrong folder | An older `export KIT` line is used | Repeat the `echo` line in step 5b, then `source ~/.bashrc` and `echo $KIT` |
| `$KIT: unbound` or empty `echo $KIT` | Variable not set in this terminal | `source ~/.bashrc`, or repeat the `echo` line in step 5b |
| `ModuleNotFoundError: No module named 'yaml'` or `'google'` | ADK environment not active in this terminal | `source ~/adk-env/bin/activate`, then run the command again |
| `adk: command not found` | Environment not active in this terminal | `source ~/adk-env/bin/activate` |
| Empty drop-down on the chat page | Server started from the wrong folder | `Ctrl + C`, `cd "$KIT/agents"`, start again |
| `PERMISSION_DENIED` / `403` in the reply | Identity cannot call Vertex AI in this project | `bash "$KIT/setup.sh"` and follow what it prints |
| `SERVICE_DISABLED` | Vertex AI API is off | Step 4 |
| Warning about a `quota project` that differs from your project | The second login in step 2 remembers an older project | `gcloud auth application-default set-quota-project <YOUR_PROJECT_ID>` |
| Port 8000 already in use | Old server still running | `Ctrl + C` in the old terminal, or `adk web --port 8001` |
| C-105 says `not_found` | You are on `complaints_v3_measured` | Choose `complaints_v4_context` |
| P5's second refund is not blocked | The server was restarted between the two refunds | Run both refunds without restarting |
| P5's first refund is blocked | P1 already refunded C-101, so the total was over the limit | Expected. Restart the server to reset refunds, then run P5 first |
| Test shows `FAIL` | `ontology.yaml`, the data or a test was changed | `cd "$KIT" && git checkout -- ontology.yaml data/ tests/` |
| `git pull` says local changes would be overwritten | A file was edited | `cd ~/domainFDE && git stash`, then `git pull` |
| Different wording on a second run | Normal; models vary | The `>>>` lines should still match |
