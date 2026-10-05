---
name: university-assignment
description: 'Receives a university assignment — problem set, lab report, essay, literature review, presentation, code project, proof, translation, design task — reads it, builds a source-backed brief, solves it in Persian from the student''s own material and web sources, then delivers a correctly formatted PDF with an explicit list of everything it could not verify. Use when the user hands over a course assignment, exercise, homework, project brief, lab writeup, seminar outline, or asks "solve this / do my assignment / write this report / answer these questions". Strict mode: nothing is stated that was not retrieved or computed; gaps are marked, never invented.'
---

# University assignment

Takes an assignment and produces a submittable document in Persian, built from the student's own material plus whatever the web can legitimately add, with every unverifiable claim marked instead of filled in.

## The one rule

**Nothing enters the file that you did not retrieve or compute.** No invented citations, no invented data, no confident recall of a fact you are unsure of. When you cannot verify something you write a placeholder — `[نیازمند داده]`, `[نیازمند منبع]`, `[نیازمند تأیید استاد]`, `[حل نشد]` — and it goes into the delivery note.

A visible gap costs the student one sentence. A confident invention costs them the grade and they will never see it. Full rules and the pre-delivery checklist: `references/integrity.md`.

## Layout

- `references/integrity.md` — the strict-mode rules, the specific traps, the checklist to run before every delivery
- `references/assignment-types.md` — the playbook per assignment type: what each one must contain and how it usually goes wrong
- `references/persian-output.md` — house style: RTL, digits, ZWNJ, punctuation, units, how to write formulas with no TeX engine
- `assets/brief-template.md` — the working brief you fill in after reading the assignment
- `assets/delivery-template.md` — the delivery note, including the mandatory unverified list
- `scripts/render.py` — Markdown/HTML → PDF via headless Chrome/Edge. Zero dependencies.

## Workflow

### 1. Intake — read it, never assume

Get the assignment text. It may arrive as a PDF, a Word file, an image of a printed sheet, pasted text, or a description. Extract it before doing anything else. If it is illegible or truncated, say so and ask — do not reconstruct a plausible-looking prompt and solve that instead.

Then read it for the constraints, because these decide the deliverable and they are the part students miss:

- output format (`در قالب Word` → `.docx`, `فایل PDF` → PDF, `اسلاید` → slides)
- length or page budget
- required sections, in the order the course wants them
- citation style — **and whether it wants references at all**
- what is allowed: course material only? external sources permitted? AI use banned?

**If the assignment does not specify a format, deliver PDF.** If it bans AI help, say so once, in one line, and offer what remains legitimate: understanding the method, checking their work, finding their errors, explaining a concept.

### 2. Brief

**If the `sharif-cw` skill already ran, the brief exists.** `cwtrack brief --cmid <id>`
creates a working folder with `brief.md` pre-filled with everything the site knows —
title, course, term, deadline, countdown, status, link — plus `source/` for material,
`draft.md` for the answer and `HANDOFF.md` with the next steps.

Work in that folder. Its `brief.md` section ۲ (the assignment text) is deliberately
empty, because the site does not expose it. Fill it in — from the assignment page or
the lecturer's material — and treat everything else in the file as already-verified.
Do not re-derive the deadline, and do not trust it blindly either: if the brief's
deadline disagrees with the page, say so.

Otherwise, copy `assets/brief-template.md` next to the work, fill it in, and keep it.
Either way it holds the assignment text, the extracted constraints, the open
questions, the assumptions, and the source ledger.

Give the student the brief before writing anything substantial **when the assignment is large, ambiguous, or the approach has more than one reasonable fork** — one round trip is cheaper than a wrong document. When the assignment is small and clear, state the approach in a sentence and continue; do not make them confirm what they already asked for.

### 3. Sources — the student's material first

Their course material is authoritative. Web fills gaps; it does not replace.

1. Everything they gave you: slides, جزوه, textbook chapters, previous homework, the lab manual. Read it properly, not by skimming.
2. Web, only for what is missing: an unfamiliar formula, a convention you need to check, primary literature for an essay. Search in Persian and English — Persian sources often carry the local convention and the local vocabulary.

Log every source in the brief's ledger with a stable id (`S1`, `S2`, …). This ledger is what makes the document auditable *for you*, and it costs the student nothing.

**On citations:** most assignments do not want a bibliography, and an unrequested one is noise. So do not print references unless the assignment asks. Keep the ledger anyway, and add every source to the delivery note as a courtesy list — the student then has provenance without a bibliography cluttering the submission. When the assignment *does* want references, produce a real one from sources you actually opened; a bibliography generated from memory is the single worst thing this skill can emit.

### 4. Solve

Pick the playbook from `references/assignment-types.md` and follow it. The recurring requirements across all types: state what is given with units, show the work rather than asserting the result, and mark every input you were not given.

Some things are the student's to produce and yours to demand: measurements, survey results, personal reflection, and the parts where the assignment is testing their own reasoning. Hand those back with `[نیازمند داده]` and say what to measure. Never fill a data table with plausible numbers — not even clearly-labelled examples inside the delivered document.

### 5. Render

Write the document as Markdown in the same folder as the brief. Then:

```bash
python scripts/render.py draft.md --title "..." --subtitle "..." --footer "نیم‌سال اول ۱۴۰۴"
```

- Output PDF path defaults to the source stem. Verify it exists and is non-trivial — the script exits non-zero and says why if it fails.
- Standalone digits become Persian (`12` → `۱۲`); identifiers stay Latin (`COVID-19`, `ISO-8601`, `3.14.7`). `--digits latin` for a mostly-Latin document.
- Vazirmatn is bundled in `assets/fonts/` and embedded into the PDF automatically. `--font system` opts out and uses whatever the machine has installed, which is worse for Persian but produces a much smaller intermediate HTML.
- `.docx` is required when the course says Word. Write the Markdown anyway — it stays the editable master — then convert with the `docx` skill if installed, otherwise say plainly that the Markdown is the deliverable and offer to format it if they install one.
- Slides are not this script's job. Use python-pptx or the `pptx` skill, and open the result to confirm it renders.
- Real typeset math needs the LaTeX path (`xelatex` is present); raise it before switching, it needs one setup round-trip. See `references/persian-output.md`.
- **The upload is the student's.** Nothing here submits anything anywhere, and nothing should gain that ability. When the work is done, tell them to upload it themselves, in their browser, after reading it. The deadline in the brief is theirs to check — this skill does not remind them.

### 6. Audit and deliver

Run the checklist in `references/integrity.md`. Then fill in `assets/delivery-template.md` and hand over both.

The delivery note is not a formality. The student needs to know which parts are unfinished, which claims you could not verify, and which sections they must write themselves — otherwise they will submit a `[نیازمند داده]` placeholder without noticing.

If the assignment named a page or word limit and the document does not fit, **cut explicitly, never silently.** Say what you shortened and what you sacrificed.

## Persian output

Follow `references/persian-output.md`. The three that get violated most: use ZWNJ (`می‌شود`, `به‌طور`, `نمی‌توان`); use `،` and `؟` and `؛` not Latin punctuation; write formulas Unicode-first (`F = k·Δx`, `∂u/∂t = α∇²u`) because the PDF pipeline has **no TeX engine** and prints formula source verbatim.

## Boundaries

This produces study-ready drafts and worked solutions. For graded work the student has to defend, say which sections they should write themselves so they can answer follow-up questions, and note their institution's AI policy once rather than repeatedly. If they ask for something aimed at misrepresenting authorship on an exam or circumventing a stated integrity rule, decline that part and offer the legitimate help around it.
