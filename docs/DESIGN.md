# Personal HQ – workspace design

This is the design the scripts build. It comes from 33 pages of your notebook
(16 Sep – 22 Oct 2026). The exact schema lives in
[`src/personal_hq/schema.py`](../src/personal_hq/schema.py), and this document explains it.

## 1. What your notes showed, and how the design follows them

| In your notebook | In Notion |
|---|---|
| One page per day: a checklist, sometimes with time slots | **Tasks**, one record per line, with `Planned` date and `Time` |
| ✓ / ☒ / empty boxes, and the "6/11 done" scores | `Status` (To do · Done · Not done · Dropped · Needs review), plus `Source mark` keeping the original mark |
| Green-ink evening review: actual times, reasons, lessons | `Notes` field on each task; reflections go in the **Notes** database |
| "– ☐" items carried over from an earlier day | `Carried over` checkbox, and a **Carried over** view |
| Day names next to missed items ("Mon", "Tue") | Change `Planned` to the new day. The original record keeps its history if you mark it Not done and add a new one. |
| "GOALS THIS WEEK (05–11 Oct)" pages with sub-goals and deadlines | **Goals** with `Horizon = Week`, linked to a **Weeks** page; sub-goals use `Parent goal` |
| Threads running for weeks (literature review, Zindi, honours paper…) | **Projects**, so a task shows what it contributes to |
| "roadmaps (short, mid & long term)" on 30 Sep | `Horizon` includes Long-term, Semester and Month, ready for your roadmap |
| Some things keep slipping (Hands-On ML ch. 2: 6 times, 0 done) | **Slipped (not done)** view (group it by Project in Notion, see §5), plus the weekly-review prompt |

I deliberately left out a habit tracker, a separate database per time
horizon, priority scores and a knowledge base. The notes don't use them, and
each would be one more thing to maintain. Running and wake-up times stay as
ordinary tasks and weekly goals ("4 runs → 3 (4 km) + 1 (8 km)"), which is
how you already track them.

## 2. Page hierarchy

```
Personal HQ  (your existing page – kept as is; dashboard appended at the end)
├── … your existing content (untouched) …
├── 🧭 dashboard callout ("Start here every day")
├── ☀️ Today            → linked Tasks view
├── ⏰ Overdue          → linked Tasks view
├── 📅 Next 7 days      → linked Tasks view
├── 🎯 This week's goals → linked Goals view
├── 📁 Active projects  → linked Projects view
├── 📥 Capture          → linked Notes view
├── 🔁 Weekly review    → checklist + linked Weeks view
└── 🗂️ Personal HQ System  (child page)
    ├── ✅ Tasks     ├── 🎯 Goals     ├── 📁 Projects
    ├── 🗓️ Weeks     └── 📝 Notes
```

## 3. Databases

**Tasks**: what you intend to do on a day, and what happened.

| Property | Type | Why |
|---|---|---|
| Task | title | the line as written |
| Status | select | To do · Done · Not done · Dropped · Needs review |
| Planned | date | the day it's on your list (drives Today / Overdue) |
| Completed on | date | the actual date/time the task was completed; written by the Notion Complete button |
| Due | date | only when a real deadline differs from the planned day |
| Focus | checkbox | your 1–3 most important tasks today (the `*` habit) |
| Time | text | time slots as you write them ("05:05–05:20") |
| Area | select | life area |
| Project / Goal | relation | why this task matters |
| Carried over | checkbox | moved from an earlier day |
| Notes | text | margin notes, reasons, uncertainty |
| Source mark · Source · Import ID | select / text | where the record came from, and stops duplicates on reruns |
| Completed | formula | `Status = Done`; feeds the progress rollups |

The `Completed on` value is intentionally captured in Notion rather than
reconstructed by Python. Configure a Tasks database button named **Complete**
to set `Status = Done` and then set `Completed on = Now`. A Notion database
automation triggered when Status is set to Done can provide the same behavior
if that feature is available in the workspace. The Python API can create the
date property, but it cannot create the button or automation. When the heatmap
updater first encounters older Done tasks with an empty `Completed on`, it
uses each task's `Planned` date as the historical completion date. It never
overwrites a non-empty completion date.

**Goals**: Goal, Horizon (Long-term · Semester · Month · Week), Status
(Active · Achieved · Missed · Dropped · Needs review), Area, Target date,
Project, Week, Parent goal, Tasks, Notes, **Task completion**, Source, Import ID.

**Projects**: Project, Status (Active · On hold · Done · Dropped · Needs review),
Area, Outcome, Next action, Start, Target, Tasks, Goals, Notes,
**Task completion**, Import ID.

**Weeks**: Week, Dates, Focus, Wins, What slipped & why, Lessons, Adjustments, Goals.

**Notes**: Note, Type (Capture · Reflection · Learning · Log · Day review ·
Reference), Date, Area, Project, Source, Import ID. The full text is in the page body.

### Relations
`Tasks → Projects`, `Tasks → Goals`, `Goals → Projects`, `Goals → Weeks`,
`Goals → Parent goal` (one-way), `Notes → Projects`. All except Parent goal are
two-way, so each project page lists its tasks, goals and notes.

### How "Task completion" works, and its limits
`Task completion` is a rollup: the percentage of linked tasks whose Status is
Done. It counts tasks, not effort. A 5-minute task weighs the same as a
5-hour one, and a goal with no linked tasks shows 0%. Treat it as a hint, not
a score. Nothing in the system invents progress numbers.

## 4. Views

| Database | View | Filter |
|---|---|---|
| Tasks | Today | Planned = today, not Dropped (sorted by Time) |
| Tasks | Upcoming | Planned in the next 7 days |
| Tasks | Overdue | Planned before today **and** still To do |
| Tasks | Inbox (unplanned) | no Planned date, To do |
| Tasks | Calendar | calendar by Planned |
| Tasks | Carried over | Carried over ✓ |
| Tasks | Slipped (not done) | Status = Not done, sorted by Area then date |
| Tasks | Completed | Status = Done |
| Tasks | Needs review | Status = Needs review (imported items to check against the notebook) |
| Goals | Open weekly goals | Horizon = Week and Active / Needs review |
| Goals | All goals by horizon | sorted by Horizon |
| Projects | Active projects | Active / Needs review |
| Notes | Capture inbox · Reflections & learnings | by Type |
| Weeks | All weeks | newest first |

The date filters are relative ("today", "one week from now"), so the
dashboard stays current with no script running.

## 5. What the API can and cannot do (checked 22 Oct 2026, API version 2026-03-11)

| Feature | How it's provided |
|---|---|
| Pages, databases, properties, relations, formula, rollups | Created by the Python setup (API) |
| Database views (table, calendar) with filters and sorts | Created by the setup (Views API, March 2026) |
| Linked views on the Personal HQ page | Created by the setup (`create_database` in Create View) |
| Everyday use: adding, ticking, rescheduling, reviewing | **Entirely in Notion**, no Python |
| Activity heatmap | Manual `scripts/update_activity_heatmap.py --apply`; reads live Tasks by `Completed on` and inserts a native table before Today |
| Weekly page for next week | Manual in Notion, or `scripts/new_week.py` (optional) |
| Recurring tasks (e.g. "10 km run" every Saturday) | **Manual in Notion**: database template → *Repeat*. The API cannot create repeating templates. |
| Notion automations / buttons | **Manual in Notion**; the public API cannot create them |
| Board views grouped by Status; grouping "Slipped" by Project | Manual (view ⋯ → Group → Project): the API's group-by format isn't fully documented, and relations can't be sorted, so I avoided it |
| Column layouts, cover images, view tab order | Manual, cosmetic |
| Heatmap scheduling | **Manual by choice**: run `scripts/update_activity_heatmap.py --apply` at the end of each day; no cron or hosting is required |

If any step is rejected by Notion (for example, if a view type behaves
differently from the documentation), the script doesn't stop. It reports the
failure and prints the exact manual step instead.

## 6. Interpretation defaults applied to the import

You chose "move on till the end" at the Phase 2 checkpoint, so these proposed
defaults were applied. Each one is reversible: the original mark is kept on
every record.

1. ✓ = Done, ☒ = Not done (supported by "6/11 done" on 16 Sep). Boxes whose mark
   I couldn't identify as ✓ or ☒ at the photo's resolution (153) are imported
   as **Done**. They keep `Source mark = marked`, so you can filter and re-check them.
2. Empty box on a past page = Not done; on 22 Oct (today) or in this week's
   goals = To do / Active.
3. Filled or unreadable boxes (8) = **Needs review**, never guessed.
4. A "–" before the box = `Carried over`.
5. The undated "weekend" page is planned on 26 Sep. The two items above the
   05–11 Oct weekly goals are planned on 4 Oct. Both say so in their Notes.
6. Pages with a second date written underneath (18/19 Sep, 10/11 Oct) are
   planned on the first date, with a note.
7. The nine life areas and 23 projects are my grouping (`data/mapping/projects.json`).
   All projects are imported with Status **Needs review** so you set the real status yourself.
8. Lip-reading (CV class) and the final-year project (video datasets / exam
   malpractice) are separate projects.
9. 72 uncertain readings keep an "Uncertain reading: …" note. Names were not corrected.

## 7. Trade-offs

* **Select instead of Notion's Status type.** The API can't reliably create
  Status options, and select filters work the same way.
* **Databases live on a child page,** so the Personal HQ page stays a clean
  dashboard of linked views.
* **One task record per day it was planned,** rather than moving one record
  through time. This preserves "what I intended vs what happened", at the cost
  of a few near-duplicate titles (e.g. "continue zindi" appears 14 times on
  different days). That repetition is the pattern your weekly review should notice.
