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
- `references/persian-output.md` — house style: RTL, digits, ZWNJ, punctuation, units and typeset mathematics
- `assets/brief-template.md` — the working brief you fill in after reading the assignment
- `assets/delivery-template.md` — the delivery note, including the mandatory unverified list
- `references/latex-reports.md` — default PDF workflow using the local Sharif template library, XeLaTeX, and archived sources.
- `scripts/render.py` — legacy Markdown/HTML renderer, only for an explicit assignment exception.

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

**When `sharif-cw` supplies a `work_id`, resume the saved work first.** Call
`api.work_get(work_id)` and use its `workspace` folder for the brief, working files and
drafts. The saved `input` contains the selected course, assignment text, deadline and
source; `attachments` contains immutable copies of the original files. Read every
prompt attachment before solving. Use `api.materials_text(course_id)` for legacy CW
course materials. For the shared course catalog, inspect the `resources` returned by
`api.study_prepare()` or `api.resource_view(target=...)`. Open and read the captured
artifact itself before using it; registration or capture alone is not evidence of use.
Record the exact snapshot, used extent, parts, answer sections and requirements in
`work_save(resource_uses=...)`, then keep the source ledger in the brief.

For a shared CW/Quera task, also inspect every `course_sources` entry returned by
`study_prepare`. Resolve `link_required` with the course code and term when available;
if the identity remains ambiguous, ask once and keep source coverage incomplete until
the student resolves it. Read resources from linked CW offerings as well as the task's
own platform. Treat `local_library_only` as registered local material, not proof that
the connected platform page was checked. Preserve `not_configured`, `needs_refresh`,
`no_candidate`, authentication challenges and partial coverage as separate evidence;
never replace them with “no course materials.”

If the intake has open questions or the prompt is missing, ask for the missing text or
clarification. For missing or changed assignment text, collect the updated input and
persist it with `work_sync`; for another clarification, record the answer in the saved
work sections and clear the resolved question through `work_save`. A PDF or image
attachment is not extracted merely because it was received. Never solve an empty or
unreadable prompt.

For the older brief-only flow, `sharif-cw` may still provide a `brief.md` folder from
`api.make_brief(cmid=...)`. In that flow, fill section ۲ from the assignment page or
lecturer's material before solving. Treat its title, course and deadline as retrieved
data, and report a disagreement with the assignment page. Otherwise, copy
`assets/brief-template.md` to the working folder and fill it in. The brief holds the
assignment text, extracted constraints, open questions, assumptions and source ledger.

Give the student the brief before writing anything substantial **when the assignment is large, ambiguous, or the approach has more than one reasonable fork** — one round trip is cheaper than a wrong document. When the assignment is small and clear, state the approach in a sentence and continue; do not make them confirm what they already asked for.

### 2a. Persistent course principles — infer from the conversation

At the start of every assignment, review the available conversation history for
course-specific requirements the student expects to carry into later work. Do not
wait for the student to say “save this” or “add this as a principle.” Treat language
such as “always,” “for every experiment,” “must,” firm corrections to a previous
deliverable, and repeated preferences as strong evidence of a durable principle.

Separate a reusable course rule from a one-assignment choice. Keep deadlines,
experiment-specific designs, one-time formatting requests and a team roster that may
change with the current task unless the student clearly says they recur. When evidence
is strong, update that course offering’s local principles file, add a dated history
entry with the conversational or official-source basis, and capture a new immutable
resource snapshot through `api.resource_capture()`. Keep earlier snapshots for
auditability. When evidence is ambiguous and would materially change future work, ask
one concise clarification; otherwise keep it task-scoped and continue.

Before solving, read the newest captured principles snapshot attached to the exact
course offering, along with the current assignment and official course material. A
principle supplements those sources and does not replace them. Do not apply a rule to
another offering merely because its course name is similar. After adding a principle,
verify that the new snapshot is visible from `api.resource_view(target=...)` and
refresh the resource dashboard when applicable.

### 3. Sources — the student's material first

Their course material is authoritative. Web fills gaps; it does not replace.

1. Everything they gave you: slides, جزوه, textbook chapters, previous homework, the lab manual, and captured resources attached to the selected course or task. Read the actual files and selected extent, not just the resource registry.
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

**Every assignment PDF uses a LaTeX template unless the assignment explicitly requires a different format or template.** The agent chooses per assignment; templates are not bound to courses. Read `references/latex-reports.md` before producing any PDF. The initial library contains the approved Sharif exercise without cover, exercise with cover, and project report templates. Preserve their appearance while adapting their sample content to a student answer.

Use `api.report_templates`, `api.report_prepare` and `api.report_build` for saved work. Write the actual answer as LaTeX in the returned `content_path`, keeping figures, bibliography and other dependencies inside that project. Save academic sections before building. Each build freezes its source and keeps a complete source ZIP beside the PDF. The selected template, upstream hash, recipe version, selection reason and build result are saved in the work history.

A successful build is `under_verification`, not student-ready. Inspect the PDF and source bundle, then record evidence for both `pdf` and `latex_source`, including the returned `report_basis_digest`. After changing source, template or answer, rebuild and verify the affected outputs.

A failed build is checkpointed as `needs_completion` with its diagnostics and available source. Resolve dependencies or source errors and retry. Preserve unfinished work and disclose any remaining blocker. Use the legacy HTML renderer only when an explicit assignment requirement authorizes that exception; compiler failure does not authorize it.

For work without a `work_id`, first create a manual work record with the received assignment so the same template and source history applies. An explicitly required Word or slide file still follows that format's own artifact workflow and supplied template.

**The upload is the student's.** Tell them to read the final files and upload them in their own browser.

### 6. Audit and deliver

Run the checklist in `references/integrity.md`. Then fill in `assets/delivery-template.md` and hand over both.

**Audit the delivered file, not your source string.** Read the `.docx` runs and the text extracted from the final PDF, then assert on those: zero `COMBINING` matches (`## 0.d`), one complex-script font across the document (`## 0`), zero instructional residue or meta-commentary (`## 0.b`). Auditing the string you generated proves nothing — this catches marks that arrived from a transcribed boilerplate passage and from the render path, both of which have happened.

The delivery note is not a formality. The student needs to know which parts are unfinished, which claims you could not verify, and which sections they must write themselves — otherwise they will submit a `[نیازمند داده]` placeholder without noticing.

For a saved `work_id`, persist the requirements, sources, answer sections, open
questions and limitations with `api.work_save`. Save the answer before running checks,
then use the returned `input_fingerprint` and `answer_fingerprint` in each check record
so evidence is tied to the exact input and answer that were examined. A requirement
has `id`, `description`, `deliverable_roles` and `verification_method`; a check has
`requirement_id`, the matching `method`, `result` (`pass`, `fail` or `not_run`),
`evidence`, both content fingerprints, `report_basis_digest` for templated PDFs, and `deliverables` listing each inspected
file's role and SHA-256. Hash every file you intend to deliver and inspect it; an
unlisted output keeps the work in `needs_completion`. Save the checks, then call
`api.work_finish` with those output paths and roles plus the delivery note. The API
copies those files into the immutable work
history and returns either
`ready_for_student_review` or `needs_completion`. Only describe the work as ready for
student review when the API returns `status="ok"`; address or disclose every gap it
returns. After editing the answer or receiving a changed prompt, rerun affected checks.

If the assignment named a page or word limit and the document does not fit, **cut explicitly, never silently.** Say what you shortened and what you sacrificed.

## Persian output

Read `references/persian-output.md`. The four that get violated most:

- **No tashkeel, ever** (`## 0.d`) — no fatha, kasra, damma, tanween, shadda, sukun, superscript alef, and no hamza-above on a bare `ه`. Persian students type `مهندسی`, never `مهندسی`, so marks read as machine-generated before the content does. Strip them programmatically; do not trust your eye.
- **A template beats this file's style** (`## 0`) — the course's font, sizes and wording are the spec.
- **The document stands alone** (`## 0.b`) — no `[نیازمند …]`, no helper text, no reference to the writing process, on the page.
- **ZWNJ for correctness** (`می‌شود`, `به‌طور`, `نمی‌توان`) regardless of document type. Typeset formulas with LaTeX math environments in the selected template; keep Latin terms and code in the proper direction.

Punctuation is the fourth axis and it is **proportional**: a problem set or form gets periods and little else (`## 0.e`), an essay gets normal Persian punctuation, a research article gets the full formal set. Do not default to tidy prose punctuation — on a simple assignment it is a signature.

## Boundaries

This produces study-ready drafts and worked solutions. For graded work the student has to defend, say which sections they should write themselves so they can answer follow-up questions, and note their institution's AI policy once rather than repeatedly. If they ask for something aimed at misrepresenting authorship on an exam or circumventing a stated integrity rule, decline that part and offer the legitimate help around it.
