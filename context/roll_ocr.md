# Roll PDFs (OCR)

Reading election office roll PDFs into the import CSV. Tasks: Step 13 in `docs/plan.md` (after the 25 Nov demo). In scope from SRS version 1.1 (12 Nov). Nothing is built yet.

## The files (12 Nov, part 49; counts only)

- Every page is one image with no text: 30 pages, each 949 × 1343 RGB, **115 dpi**, losslessly compressed (no JPEG damage), no fonts. Producer iText, so made as images on purpose. Copying text or "fixing fonts" can never work.
- Layout: English, 3 × 10 grid = 30 voter boxes per voter page; a box is about 316 × 120 pixels and letters are about **6 pixels tall** (OCR wants 20–30). Each box: serial, EPIC, name, father / husband / mother name, house no, age, gender. Page header: AC, part, section. First page = cover; last pages = summary with the total voter count.
- Answer key: the 51 hand-made CSVs in `jansetu-private/` (35 columns; what `scripts/import_roll_parts.py` takes). Part 49: 668 voters, serials 1–668 without gaps, 9 deleted, 1 supplement addition, names plain English. The part 4 CSV is a copy of part 3: do not use it as a key.
- On the laptop only 3 PDFs (12 Nov): part 49 on the Desktop, parts 35 and 4 in `Desktop/trash`. They belong in `jansetu-private/`.

## Decisions (12 Nov)

- Free, open-source tools on our own machines only. No paid OCR or AI APIs; voter data never leaves our machines. An AI helper is optional, local and off by default (13.9).
- Pipeline: page images out of the PDF at their own size (`pikepdf`) → page types → OpenCV cuts the 30 boxes (grid lines, layout profile as fallback) → each field enlarged 3–4 times → Tesseract 5 `tessdata_best` per field (digits only for serial and age) → second reader (PaddleOCR) → rules (EPIC by position: 3 letters + 7 digits; Devanagari digits; Unicode normalised) → checks → CSV + private review file + report with counts only.
- Accept a field when both readers agree; otherwise review. Never guess an unknown layout: refuse the PDF.
- A part whose count does not match its summary page is never imported automatically.
- Tune on parts 1–35, test on 36–51. Report per field: exact, sent to review, silent errors (wrong and not flagged). Targets: EPIC and age exact with zero silent errors; every field 99%+.
- One library, two ways in: batch script (folder, shards by file name across machines, resume by file hash, no database), then admin upload through `POST /rolls/imports` (super admin) into `roll_import_rows`. OCR packages in `requirements-ocr.txt` and an optional `ocr-worker` container, off by default.
- SRS promise: reading English-layout PDFs with checks and a review list. No accuracy figure promised. Marathi only after a sample and a checked list arrive.

## Rough speed (estimates until 13.1 measures)

| | Per page | 30-page part | 51 parts (~1,400 pages) |
|---|---|---|---|
| Tesseract only, 1 core | 10–15 s | 5–8 min | |
| Two readers, 1 core | 20–35 s | 10–18 min | |
| Two readers, laptop, 6 workers + GPU | 3–6 s | 2–3 min | 1.5–2.5 h |

30–35 lakh voters ≈ 1.1–1.25 lakh pages ≈ 600–1,200 core-hours. Not on the live KVM 4 during field work. Review time costs more than CPU: 1% to review at 33 lakh = 33,000 rows.

## Pitfalls

- Never print names, EPICs or box images; counts and percentages only. Box images are voter data: private folders, never in git, deleted after the import is applied.
- 115 dpi: names are the hard field; EPIC and age are short and rule-checked.
- Marathi: free OCR is weaker on Devanagari vowel signs and joined letters at this size; no answer key yet.
- "DELETED" stamps cover text; supplement pages look different.
- The answer key has its own mistakes; sample disagreements by eye before blaming the OCR.

## Waiting for

- All 51 AC 2 PDFs in `jansetu-private/`; the 3 on the Desktop moved there.
- How the 51 CSVs were made (typed or by a tool).
- A Maharashtra sample (2–3 part PDFs) and a checked list of about 1,000 voters.
- OK to install Tesseract, PaddleOCR, OpenCV; which machines run big batches; may the laptop GPU be used.
- Review rule: import a part's clean rows first, or hold the whole part until its review rows are done.
