# Assignment PDF templates

Use the local LaTeX library for every assignment PDF unless the assignment explicitly specifies another template or format. This decision is already authorized for this project; it needs no repeated approval. The agent selects the template for the current assignment and records why.

## Select and prepare

Read the assignment's requirements and any supplied template first. List choices with `api.report_templates(data=...)`; this is offline and does not create files. Choose `sharif-exercise` for a compact exercise answer, `sharif-exercise-cover` when a separate title page fits, or `sharif-project-report` for project/lab reports. All are Persian templates; use proper Latin environments for English passages. A genuinely different explicit requirement follows the supplied format rather than forcing one of these choices.

```python
current = api.work_get(work_id, data=data)
prepared = api.report_prepare(
    work_id,
    "sharif-exercise",
    metadata={"title": actual_title, "authors": actual_authors,
              "course": actual_course, "term": actual_term},
    reason="Explain why this layout fits the assignment requirements.",
    expected_revision=current["revision"],
    data=data,
)
```

Metadata is plain text, escaped by the API. Available keys are `title`, `english_title`, `authors` (a list), `course`, `term`, `professor`, `department`, `university`, and `date`. Use only known values; omit unknown optional fields. No sample identity is inherited from upstream.

The first preparation downloads pinned source ZIPs into `.cw/latex-templates/` beside the selected data store. Later preparations reuse these verified bytes. The original XB Niloofar font family is separately cached from its Font Library distribution, pinned by hash and copied with its OFL notices into every source project. The modified font shipped in the Sharif report archive produced incorrect Persian glyphs in local rendering, so the recipe uses the original version of the same face. Updated remote bytes require a deliberate new template version; they never silently replace a cached version. Upstream attribution/notices stay with the locally received source. A template-wide upstream license has not been declared; the repository distributes catalogue/recipe code, not those third-party ZIPs or fonts.

`prepared["project"]` is a fresh editable folder. Write actual LaTeX to `prepared["content_path"]`, keeping images, bibliography and other document inputs inside that folder with relative paths. The initial content file is empty and cannot build until an answer is written. Exercise content may use `questions`, `question` and `solution` environments; answers are enabled. Report content uses sections. Sample questions, grades, report prose and references are not the answer.

The upstream layouts remain the base. The preparation recipe replaces sample metadata/content and repairs missing font names, package setup and article-incompatible definitions. It leaves general PSTricks drawing support opt-in; generated diagrams should normally be ordinary embedded files. Inspect any further formatting change in the final PDF.

## Save, build and repair

Save academic answer sections and requirements through `api.work_save` before building; include required roles `pdf` and `latex_source` with an appropriate verification method. Use the latest returned revision:

```python
built = api.report_build(work_id, expected_revision=latest_revision, data=data)
```

Each call freezes the whole source tree in a separate attempt folder and creates a source ZIP. It runs XeLaTeX without shell escape or interactive input, with a timeout per tool process. MiKTeX's automatic installer is disabled for this API call, so a missing package returns diagnostics instead of opening a prompt. If bibliography data is present, BibTeX runs between LaTeX passes. Required TeX packages are external dependencies, not Python runtime dependencies.

On `needs_completion`, read the returned message and the saved report's log path (relative to the work folder). Fix source or install the specific missing dependency from the official TeX distribution, then retry from the editable project with the newest revision. Keep the selected layout. Build failures and their source attempts remain available; there is no automatic HTML fallback.

On `built`, use `built["files"]`: one `pdf`, one `latex_source`. Success means compilation succeeded; it does not certify the answer or document layout. Every output is a new attempt, so later source edits/builds preserve earlier files.

## Verify and deliver

Read/render the actual PDF using the PDF skill. Check every relevant page, Persian/Latin direction, math, figures, tables, code, names, labels, references, page breaks and the absence of sample content or instructional residue. Open the ZIP and check that it contains the full editable project, nested assets, local fonts, `report.json` and `BUILD.md`. For nontrivial dependencies, rebuild an extracted bundle to confirm completeness.

Checks saved with `api.work_save` must include the current `report_basis_digest`, as well as `input_fingerprint`, `answer_fingerprint`, the requirement's method, substantive evidence, and role/SHA-256 pairs for both actual files. The returned digest binds evidence to this template and build. Rebuild after changing academic content, and repeat affected checks after source/template changes. `work_finish` requires the PDF and ZIP from the current successful build and matching checks; a previous successful delivery cannot make a failed/prepared/new report ready.

Call `api.work_finish` with the built files and a delivery note only after checking them. The existing immutable delivery history preserves both files. Report `ready_for_student_review` only when finish returns `status="ok"`. A rendered PDF never counts as a platform submission.
