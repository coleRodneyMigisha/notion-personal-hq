# notion-personal-hq

Builds your personal productivity system **inside Notion**, under your
existing *Personal HQ* page, from 33 pages of your handwritten daily-goal
notes. Python is only the setup tool. Once it has run, everything works in the
normal Notion app (web, desktop, phone), even when your computer is off.

* Design and reasoning: [docs/DESIGN.md](docs/DESIGN.md)
* What was read from the screenshots: [docs/EXTRACTION_NOTES.md](docs/EXTRACTION_NOTES.md)

## Contents

```
notion-personal-hq/
├── README.md                 this guide
├── requirements.txt          pinned Python dependencies
├── .env.example              template for your secret (copy to .env)
├── data/
│   ├── screenshots/                    copies of the 33 original notebook photos
│   ├── manifests/source_manifest.csv   the 33 screenshots: filename, checksum, date, status
│   ├── extracted/extraction.json       reviewed transcription (the import source)
│   ├── extracted/items.csv             the same, as a spreadsheet for review/corrections
│   ├── extracted/threads.csv           recurring tasks across days
│   ├── mapping/projects.json           which threads become Projects (edit freely)
│   └── state/notion_state.json         created by --apply: IDs of what was built (don't edit)
├── scripts/                  the commands you run (all dry-run unless --apply)
├── src/personal_hq/          the code behind them
├── tests/                    automated tests (no network, never touch Notion)
└── docs/
```

---

## 1. One-time setup on Ubuntu

### 1.1 Get the project onto your machine

Unzip it under `~/Code`:

```bash
mkdir -p ~/Code                                     # a home for your projects
cd ~/Code
unzip ~/Downloads/notion-personal-hq.zip            # creates ~/Code/notion-personal-hq
cd notion-personal-hq
```

### 1.2 Create a virtual environment and install dependencies

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip   # Python 3.10+ (once per machine)
python3 -m venv .venv                     # private Python environment for this project
source .venv/bin/activate                 # use it (your prompt shows "(.venv)")
pip install --upgrade pip
pip install -r requirements.txt           # notion-client, python-dotenv, Pillow, pytest
```

Run `source .venv/bin/activate` again every time you open a new terminal for this project.

### 1.3 Store your Notion secret safely

```bash
cp .env.example .env        # your private config file (ignored by git)
chmod 600 .env              # only your user can read it
nano .env                   # replace ntn_replace_with_your_secret with your real secret, then Ctrl+O, Enter, Ctrl+X
```

The secret only ever goes in `.env`. Don't paste it into chats, code,
screenshots or commit messages. If it leaks, open
<https://www.notion.so/profile/integrations>, open your integration, and
**refresh** the secret.

### 1.4 Give the integration access to Personal HQ

A page URL alone grants the integration nothing. You need to connect it to the page:

1. At <https://www.notion.so/profile/integrations>, open your integration's
   **Capabilities** and make sure **Read content, Update content and Insert content** are enabled.
2. Open **Personal HQ** in Notion → click **•••** (top right) → **Connections**
   → find your integration → **Confirm**.

Then check it (this is read-only):

```bash
python scripts/check_access.py
```

You should see `OK - the integration can read 'Personal HQ'`. If you see
`NO ACCESS`, the message says what to fix. The build scripts refuse to run
until this works, and they never fall back to a different page.

### 1.5 Run the tests

```bash
python -m pytest
```

Expected: `68 passed`. The tests use a fake in-memory Notion and cannot change your workspace.

---

## 2. First deployment

### 2.1 Dry run: see exactly what will happen

```bash
python scripts/deploy.py
```

This reads your workspace (with the access you just granted) and prints every
page, database, property, relation, view and record it **would** create.
Nothing is written. The full list of planned API calls, with their exact
request bodies, is saved in `logs/deploy-report-<time>.json`.

What it plans (the same plan was verified offline on 22 Oct 2026):

| Item | Count |
|---|---|
| Child page "Personal HQ System" | 1 |
| Databases (Tasks, Goals, Projects, Weeks, Notes) | 5 |
| Relations / formula / rollups | 6 / 1 / 2 |
| Views inside the databases | 15 |
| Dashboard: 22 blocks appended **after** your existing content, plus 7 linked views | 1 |
| Weeks / Projects / Goals / Tasks / Notes records | 3 / 23 / 37 / 248 / 27 |
| **Total writes** | **376**, nothing deleted, no existing block edited |

### 2.2 Apply

```bash
python scripts/deploy.py --apply
```

This takes 2–3 minutes; the scripts stay under Notion's rate limit. If it's
interrupted (network, laptop closed, Ctrl+C), **run the same command again**.
Everything already created is recorded in `data/state/notion_state.json` and
skipped.

### 2.3 Check it in Notion

Open Personal HQ and check:

- [ ] Your original content is still at the top, unchanged.
- [ ] Below it: the 🧭 callout, then sections Today, Overdue, Next 7 days, This week's goals, Active projects, Capture, Weekly review, each showing a table.
- [ ] **Today** lists the 13 tasks from your 22 Oct page (if you check on 22 Oct; otherwise it shows that day's tasks).
- [ ] **🗂️ Personal HQ System** contains the five databases.
- [ ] Open **Tasks**: the view tabs are Today, Upcoming, Overdue, Inbox, Calendar, Carried over, Slipped, Completed, Needs review.
- [ ] Open any task: Source shows e.g. `P05-02 · WhatsApp Image … 18.43.08.jpeg`.
- [ ] Open a project, e.g. **Zindi competitions**: its Tasks relation lists about 14 tasks.
- [ ] Open **Goals → Open weekly goals**: the 19–25 Oct goals are there.

If the summary listed **Manual steps**, do them now. Each one says exactly
which view or property to add and how. Then finish with the optional manual
touches in [§5](#5-what-needs-python-and-what-doesnt).

---

## 3. Using it day to day (all in Notion, no Python)

**Every morning (2 minutes)**
1. Open Personal HQ and look at **Today**.
2. Tick **Focus** on the 1–3 tasks that matter most.
3. Deal with each **Overdue** task: do it, change its `Planned` date, or set Status = Dropped.

**Adding a task.** Click **+ New** under Today (or in Tasks). Set `Planned`,
and optionally `Time`, `Project`, `Goal`, `Due`.

**Rescheduling.** Change `Planned`. To keep a record that it slipped (as your
notebook does), set the old one to **Not done** and duplicate it (⋯ →
Duplicate) with the new date and `Carried over` ticked.

**Every evening (3 minutes).** Use the task's **Complete** button when you
finish it. The button sets `Status = Done` and `Completed on = Now`. For an
unfinished task, set Status = **Not done**. Don't delete unfinished tasks:
that history is what the weekly review learns from. Write anything worth
remembering as a Note (Type = Reflection, or Capture for loose thoughts).

### 3.1 Completion dates and the activity heatmap

The Tasks database includes a `Completed on` date. Configure completion once
in Notion, because the public API cannot create Notion buttons or database
automations:

1. Open **Tasks** and add a **Button** property named `Complete`.
2. Configure the button action to edit **this page**: set `Status` to `Done`.
3. Add a second action: set `Completed on` to **Now**.
4. Save the button and use it instead of changing Status manually.

If your Notion plan exposes database automations, the equivalent is a
property-edited automation triggered when `Status` is set to `Done`, with an
action that edits `Completed on` to the current date/time. The button is the
recommended fallback because it makes the two changes together.

At the end of each day, refresh the native heatmap manually:

```bash
source .venv/bin/activate
python scripts/update_activity_heatmap.py       # dry run
python scripts/update_activity_heatmap.py --apply
```

The updater reads the live Tasks database, counts tasks by `Completed on`,
replaces its marked heatmap section, and inserts the new native Notion table
before **Today**. It never reads the extracted CSV/JSON data and does not
require hosting, cron, or a background process. On an older deployment, the
first `--apply` run adds the missing `Completed on` property and fills blank
historical completion dates from each task's `Planned` date. Existing
`Completed on` values are never overwritten.

**Every Sunday: weekly review (20 minutes)**
1. Open **Tasks → Slipped (not done)**. What keeps slipping, and why?
2. Open this week's page in **Weeks** and fill in Wins, What slipped & why, Lessons, Adjustments.
3. Set this week's goals to **Achieved** or **Missed**.
4. Create next week: **Weeks → New** (or `python scripts/new_week.py --apply`). Add 5–10 goals in **Goals** with Horizon = Week, linked to that week and to projects.
5. Plan Monday's tasks.

**Goals and projects.** Long-term, semester and month goals go in Goals with
the matching Horizon, and weekly goals link to them through `Parent goal`. A
good first job is adding the roadmap you wrote on 30 Sep. Every imported
project has Status **Needs review**, so set each to Active, On hold, Done or
Dropped, and fill in Outcome and Next action for the active ones.

**Checking the import.** **Tasks → Needs review** has 8 tasks whose box I
couldn't read. To double-check the 153 "marked" boxes imported as Done, filter
Tasks by `Source mark = marked`.

---

## 4. Maintenance

### Back up the source data
Your notes' transcription is in `data/`. Copy the whole project folder somewhere safe:

```bash
cd ~/Code
tar czf ~/notion-personal-hq-backup-$(date +%F).tar.gz --exclude=.venv --exclude=.env notion-personal-hq
```

Notion also keeps page history. You can export the workspace via **Settings → Export**.

### Rerun the scripts safely
Every script is a **dry run unless you add `--apply`**. Reruns skip anything
that exists: pages and databases are matched by title, views by name, and
records by their `Import ID`. Nothing is ever deleted.

```bash
source .venv/bin/activate
python scripts/deploy.py                     # what would change?
python scripts/create_workspace.py --apply   # re-add anything missing from the structure (e.g. a deleted view)
python scripts/import_data.py                # compare Notion against the source data
python scripts/import_data.py --apply --update   # overwrite records that differ (shows each change first in a dry run)
```

If you changed an imported task in Notion (e.g. ticked it Done), the import
reports "differs … not updated" and leaves your change alone. Only `--update`
overwrites, so normally you never use it.

### Correct the transcription
1. Edit `data/extracted/items.csv` in LibreOffice Calc. Keep the `item_id` column.
2. `python scripts/sync_review_csv.py import`: copies your edits into `extraction.json` (makes a backup first).
3. `python scripts/validate_data.py`, then `python scripts/import_data.py` (dry run) and `--apply --update` if it looks right.

### Add future screenshots or notes
1. Put the new images in a folder and run
   `python scripts/inspect_sources.py ~/path/to/folder --expected <how many>`.
   It counts them, opens each one, flags duplicates and unreadable files, and writes a manifest.
2. Transcribe them into `extraction.json` using the same structure. Continue
   the page IDs (P34, P35…) so Import IDs stay unique. An AI assistant can do
   this from the images; review the result before importing.
3. `python scripts/validate_data.py` → `python scripts/import_data.py` → `--apply`.

You don't have to keep using paper. Adding tasks directly in Notion is the normal way forward.

### Common errors

| Message | Fix |
|---|---|
| `NOTION_TOKEN is not set` | `.env` is missing or still has the placeholder; see §1.3 |
| `NO ACCESS … 404 object_not_found` | The integration isn't connected to Personal HQ; see §1.4 |
| `401 unauthorized` | The secret is wrong or was refreshed; re-copy it into `.env` |
| `403 restricted_resource` | Enable Read/Update/Insert content in the integration's capabilities |
| `429 rate_limited` | Wait a minute and rerun; the SDK already retried |
| `400 validation_error` on a view/rollup | Notion's API changed. The run continues and lists the manual step |
| `The state file belongs to parent page …` | `.env` points at a different page than the one built earlier. Fix `.env` (deliberate safety stop) |
| `appears more than once in Notion` | You have two copies of an imported record; delete one in Notion and rerun |
| `ModuleNotFoundError` | Run `source .venv/bin/activate` first |

Each run writes a log and a JSON report to `logs/`.

---

## 5. What needs Python and what doesn't

| | |
|---|---|
| **Works entirely in Notion, forever** | dashboard, views, adding/ticking/rescheduling tasks, goals, projects, weekly review, calendar, rollups |
| **Created once by the Python setup** | the System page, 5 databases, relations, formula, rollups, 15 views, dashboard blocks and 7 linked views, the imported notebook data |
| **Needs a script only if you want it** | `new_week.py` (or create the week by hand), re-importing corrected data, rebuilding something you deleted |
| **Needs an external scheduled process** | nothing. No cron job is required. |
| **Manual in Notion (optional)** | group **Tasks → Slipped (not done)** by Project (view ⋯ → Group → Project); recurring tasks (open a Tasks template → ⋯ → *Repeat*); board views; colours/covers/icons; reordering view tabs; Notion automations or buttons; plus any "Manual steps" the deploy summary printed |

## 6. For the curious: how the code is organised

* `config.py`: reads `.env` and turns the page URL into an API ID.
* `notion_api.py`: one small gateway with three implementations: real Notion,
  an in-memory fake (tests and offline runs), and a dry-run wrapper that reads
  real data but only records writes.
* `schema.py`: the whole design as data. Change it here.
* `workspace_builder.py`: creates what's missing, in order, recording progress in the state file.
* `data_mapper.py`: turns notebook items into Notion records (the interpretation rules are at the top).
* `importer.py`: creates, skips or (with `--update`) updates records by Import ID.
* `validation.py` and `sources.py`: checks run before anything is written.

The API was checked on 22 Oct 2026: version `2026-03-11`, data sources and the
Views API, through `notion-client` 3.1.0.
