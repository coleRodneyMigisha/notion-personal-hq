# Extraction notes: 33 notebook pages, 16 Sep – 22 Oct 2026

## Source verification (Phase 1)

| Source | Result |
|---|---|
| Google Drive folder | Listing visible without sign-in, but it held only **5** files (`IMG_20261022_180630_724.jpg` … `_180645_510.jpg`). The images couldn't be opened from the assistant's environment, so they were **not** counted. |
| Local folder (WhatsApp exports) | **33** JPEGs (810×1080). All open, no byte-identical or near-duplicate pairs (perceptual hash), and visual check confirmed 33 different pages. |
| Expected | 32. The owner chose to proceed with all 33. |

The 5 Drive files were never matched against the local images; they're most
likely copies of local pages. The per-file manifest, with SHA-256 checksums,
is `data/manifests/source_manifest.csv`.

## Method

Every page was read at full size, then again as 1.5× enlarged crops to tell
ticks from crosses and read margin notes. Nothing was OCR'd automatically.
Each line became one record with an ID `P<page>-<line>`, its source file, the
box mark as seen, the ink colour, any margin note, and an uncertainty note
where needed. An earlier partial transcription of 13–22 Oct
(`batch1_extraction_13-22_Oct_2026.csv`) was used as a cross-check only.

**Result: 316 records.** 248 daily tasks, 31 weekly goals + 6 sub-goals,
6 sub-points, and 25 free-text notes. 72 are flagged uncertain.

## Conventions found in the notebook

* **✓ vs ☒ in the box.** On 16 Sep every box is marked, yet the page says
  "6/11 done", with 4 clear crosses and 6–7 ticks. So ☒ appears to mean *not
  done*. Only ~28 marks were clearly distinguishable at this resolution; the
  rest are recorded as `marked`.
* **Green (and orange) ink** = added later: actual times, reasons, lessons, next steps.
* **Day names in green** ("Mon", "Tue") next to crossed items = moved to that day.
* **"–" before the box** = carried over from an earlier day. Every such item also appears on a previous page.
* **Weekly goals pages** from 5 Oct: 05–11, 12–18 and 19–25 Oct.
* **Day scores** only on 16 Sep ("6/11 done") and 17 Sep ("9½/10").

## Pages that need care

| Page | Issue | Handling |
|---|---|---|
| P07 `18.43.16 (1)` | Dated "weekend", no date | 26 Sep inferred: "wbs" and "airqo training" were open on 24 Sep |
| P15 `18.43.50` | Undated: two items, then "Goals this week 05–11 Oct" | items on 4 Oct (inferred) |
| P23 `18.43.56 (3)` | "Week's goals 12–18 Oct", no date | week range used |
| P03 / P21 | "19" / "11" written under 18 Sep / 10 Oct | first date used, noted |
| P26 | day digit overwritten | 15 Oct (between 14 and 16) |
| P05 | "22" partly unclear | 22 Sep (page order) |

No pages exist for 20, 23 and 25 Sep, or 11 Oct (unless covered by the 10 Oct page).

## Conflicts kept as-is (not resolved silently)

* 16 Sep: about 7 ticks vs "6/11 done"; "contact Mbeiza" mark is ambiguous.
* 20 Oct "finish weekly poster": marked, but the note says "haven't done Thursday".
* 20 Oct "get to department by 06:45": marked, but "reached at 06:58".
* 13 Oct "Honours posters": both ✓ and ✗ written after it.
* 19 Oct "labs 05 & 06": box empty, green tick over "06".
* Sickle-cell screening: 29 Sep empty ("they were done: tomorrow"), 30 Sep marked ("no traits").
* 5 Oct: "–" prefix on items that are ticked.
* Filled boxes: "Finish structured review" (05–11 Oct) and "Honours paper" (19–25 Oct) → Needs review.

## Readings to confirm

Kobel · Mbeiza · Mr. Syned (UCAA) · "Munyonyo declaration poster" · Dunstan ·
Ssegawa ("PE-honours") · Odur · Dru · Bel's place · "hombres" · "AFGM lock in"
· "dayclass" · "evening config" (or "routing config") · Nenna · reviewer names on
7 Oct (Bamba, Dra, Carol, Faith, Jesse, Wanja, Charis, Ezra). In Notion, each of
these records has a Notes field starting "Uncertain reading:".

## Patterns worth knowing

| Thread | Days it appears | Marked done | Not done |
|---|---|---|---|
| Hands-On ML ch. 02 | 6 | 0 | 6 |
| Zindi | 14 | 4 | 10 |
| Honours paper structure/research | 10 | 3 | 6 |
| OpenCV course | 9 | 4 | 6 |
| Structured literature review | 10 | 12 | 4 (finished, submitted 12 Oct) |
| Data Science course | 13 | 13 | 4 |

Deadline-driven coursework gets done; open-ended self-study keeps sliding forward.
