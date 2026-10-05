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

**If the `sharif-cw` skill already ran, the brief exists.** It writes a working
folder with `brief.md` pre-filled with everything the site knows — title, course,
term, deadline, countdown, status, link — plus `source/` for material, `draft.md` for
the answer and `HANDOFF.md` with the next steps. `sharif-cw` calls
`api.make_brief(cmid=<id>)` to create it.

Work in that folder. Its `brief.md` section ۲ (the assignment text) is deliberately
empty, because the site does not expose it. Fill it in — from the assignment page or
the lecturer's material — and treat everything else in the file as already-verified.
Do not re-derive the deadline, and do not trust it blindly either: if the brief's
deadline disagrees with the page, say so.

**Do not solve a brief whose section ۲ is still empty.** Ask for the assignment text
first. A confident answer to the wrong question is the expensive failure here, and in
the output it looks exactly like success.

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

Some things are the student's to produce and yours to demand: measurements, survey results, personal reflection, and the parts where the assignment is testing their own reasoning. Never fill a data table with plausible numbers — not even clearly-labelled examples inside the delivered document.

**But a placeholder is a tool, not a verdict.** It belongs in the delivery note, never on the page, and it is never a reason to hand back a half-built document. When a form has a cell you cannot honestly fill, first ask whether the assignment gives you a true *general* statement that covers it — reasoning about how a whole class of device or system works is not a fabricated measurement, and it often fills the cell honestly. If it does, write it, ship the file complete, and put the residual uncertainty in the delivery note. If it does not, one blank with an explanation beats ten invented ones.

**Read `references/persian-output.md` before writing prose.** No tashkeel ever (`## 0.d`), punctuation proportional to the document (`## 0.e`), and a voice that varies rather than repeats (`## 0.c`). These decide whether the page reads as the student's work.

### 4a. Templates — the course's own form is the spec

If the assignment ships a form, worksheet, or `docx`/`pptx` skeleton, **fill that file.** Do not author a new document in its place. See `references/persian-output.md` `## 0`: measure `w:rFonts/@w:cs` and the per-role sizes before writing a single run, then reproduce them exactly. A mismatched body font is the loudest tell in the whole file and it is entirely avoidable.

Reproduce it in both required formats: the `.docx` by filling the original in place with `python-docx`, and the PDF by hand-writing the HTML with that template's `font-family` stack — **not** `render.py`'s bundled Vazirmatn, which is the house face for documents authored from scratch and the wrong choice once a template exists.

### 5. Render

Write the document as Markdown in the same folder as the brief. Then:

```bash
python scripts/render.py draft.md --title "..." --subtitle "..." --footer "نیم‌سال اول ۱۴۰۴"
```

- Output PDF path defaults to the source stem. Verify it exists and is non-trivial — the script exits non-zero and says why if it fails.
- Standalone digits become Persian (`12` → `۱۲`); identifiers stay Latin (`COVID-19`, `ISO-8601`, `3.14.7`). `--digits latin` for a mostly-Latin document.
- Vazirmatn is bundled in `assets/fonts/` and embedded into the PDF automatically — for documents you author from scratch. **When a template exists, that template's face wins** (`## 0`, `## 4a`). `--font system` opts out and uses whatever the machine has installed, which is worse for Persian but produces a much smaller intermediate HTML.
- `.docx` is required when the course says Word. Write the Markdown anyway — it stays the editable master — then convert with the `docx` skill if installed, otherwise say plainly that the Markdown is the deliverable and offer to format it if they install one.
- Slides are not this script's job. Use python-pptx or the `pptx` skill, and open the result to confirm it renders.
- Real typeset math needs the LaTeX path (`xelatex` is present); raise it before switching, it needs one setup round-trip. See `references/persian-output.md`.
- **The upload is the student's.** Nothing here submits anything anywhere, and nothing should gain that ability. When the work is done, tell them to upload it themselves, in their browser, after reading it. The deadline in the brief is theirs to check — this skill does not remind them.

### 6. Audit and deliver

Run the checklist in `references/integrity.md`. Then fill in `assets/delivery-template.md` and hand over both.

**Audit the delivered file, not your source string.** Read the `.docx` runs and the text extracted from the final PDF, then assert on those: zero `COMBINING` matches (`## 0.d`), one complex-script font across the document (`## 0`), zero instructional residue or meta-commentary (`## 0.b`). Auditing the string you generated proves nothing — this catches marks that arrived from a transcribed boilerplate passage and from the render path, both of which have happened.

The delivery note is not a formality. The student needs to know which parts are unfinished, which claims you could not verify, and which sections they must write themselves — otherwise they will submit a `[نیازمند داده]` placeholder without noticing.

If the assignment named a page or word limit and the document does not fit, **cut explicitly, never silently.** Say what you shortened and what you sacrificed.

## Persian output

Read `references/persian-output.md`. The four that get violated most:

- **No tashkeel, ever** (`## 0.d`) — no fatha, kasra, damma, tanween, shadda, sukun, superscript alef, and no hamza-above on a bare `ه`. Persian students type `مهندسی`, never `مهندسی`, so marks read as machine-generated before the content does. Strip them programmatically; do not trust your eye.
- **A template beats this file's style** (`## 0`) — the course's font, sizes and wording are the spec.
- **The document stands alone** (`## 0.b`) — no `[نیازمند …]`, no helper text, no reference to the writing process, on the page.
- **ZWNJ for correctness** (`می‌شود`, `به‌طور`, `نمی‌توان`) regardless of document type, and formulas Unicode-first (`F = k·Δx`, `∂u/∂t = α∇²u`) because the PDF pipeline has **no TeX engine** and prints formula source verbatim.

Punctuation is the fourth axis and it is **proportional**: a problem set or form gets periods and little else (`## 0.e`), an essay gets normal Persian punctuation, a research article gets the full formal set. Do not default to tidy prose punctuation — on a simple assignment it is a signature.

## Boundaries

This produces study-ready drafts and worked solutions. For graded work the student has to defend, say which sections they should write themselves so they can answer follow-up questions, and note their institution's AI policy once rather than repeatedly. If they ask for something aimed at misrepresenting authorship on an exam or circumventing a stated integrity rule, decline that part and offer the legitimate help around it.
