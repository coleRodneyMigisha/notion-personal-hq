# Contribution Calendar

GitHub-style activity heatmap for completed tasks.

## What it is

A dedicated Notion database (`Contribution Calendar`) with one page per day.
Each page stores:

| Property   | Purpose                                      |
|------------|----------------------------------------------|
| Day        | Title (`YYYY-MM-DD`)                         |
| Date       | The calendar date                            |
| Completed  | Number of tasks marked Done that day         |
| Level      | Intensity select (None / Low / Medium / High / Very High) |
| Import ID  | `contrib-YYYY-MM-DD` for idempotent upserts  |

Levels map to counts (same buckets as the live dashboard):

- None → 0  
- Low → 1–2  
- Medium → 3–5  
- High → 6–8  
- Very High → 9+

## How it is kept up to date

```bash
python scripts/update_contribution_calendar.py          # dry-run
python scripts/update_contribution_calendar.py --apply  # write to Notion
```

The script:

1. Queries all Tasks with `Status = Done`
2. Groups by `Completed on` (falls back to `Planned`)
3. Upserts one Contribution Calendar page per day

It is safe to re-run at any time.

## Dashboard

Personal HQ shows a linked Calendar view of this database plus a short legend.
The closest native-Notion visual to a GitHub contribution graph is the
combination of the Level select colours + the Calendar view.

## Schema location

Defined in `src/personal_hq/schema.py` as the `contribution_calendar`
`DatabaseSpec` and the two associated `ViewSpec`s.
