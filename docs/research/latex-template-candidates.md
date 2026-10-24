# Sharif LaTeX template source investigation

Checked: 2026-10-24 (Asia/Tehran). This note records the original source investigation. The user subsequently approved the Sharif collection; implementation and local build acceptance are recorded in [the report design](../latex-report-design.md). The user rejected the earlier GitHub shortlist and asked to focus on [Sharif's catalogue](https://latex.sharif.edu/templates). Those GitHub templates are no longer adoption candidates.

The user wants PDF assignment deliverables to use a suitable LaTeX template unless the assignment explicitly requires something else. The agent selects the template for the assignment; there is no course binding.

## Verified downloads

The coordinating agent's later browser inspection successfully loaded actual catalogue entries and supplied their visible source-download links. The earlier observation of unresolved placeholders is superseded, not a current access blocker. These public ZIPs were downloaded and extracted to a temporary investigation folder. No included code or TeX was executed.

| Catalogue entry | Public source | Entrypoint | Source-based fit |
|---|---|---|---|
| Exercise-Template-wcover | [Covered exercise ZIP](https://latex.sharif.edu/latex/templates/6398523d2581e80097d08066/zip) | `main.tex` | Persian exercise sheet with separate title page; needs student-answer adaptation. |
| Exercise-Template-no-cover | [No-cover exercise ZIP](https://latex.sharif.edu/latex/templates/639854882581e80097d08105/zip) | `main.tex` | Persian exercise sheet with compact header; needs student-answer adaptation. |
| Course Project Report Template | [Report ZIP](https://latex.sharif.edu/latex/templates/63b3420c78d656009cf525c7/zip) | `Seminar.tex` | Persian project report with title, body, references and appendix. |

## Exercise variants

Both source comments credit Zeinab Seifoori. Both use `exam` and load `setspace`, `listings`, `graphicx`, `subfigure`, `wrapfig`, `multirow`, `geometry` and `xepersian`. No build recipe or bundled class/package distribution is supplied. XeLaTeX is a proposed validation engine inferred from XePersian use, not a tested compiler configuration.

Course, term, college and professor macros live in `main.tex`. The series heading and questions are embedded in the body. Samples include a grading table, scored questions/parts, equations, Latin text and a C listing. These are instructor exercise sheets as supplied, not separated student solution documents; answer sections and replacement of sample identities/content need explicit adaptation.

The covered variant additionally has `info.tex`, `cover-page.tex`, root `logo.png` and `images/logo.png`. Its metadata uses inherited `Thesis*` command names for title, author, supervisor, date, department and university, plus `EnglishThesisTitle`. The no-cover variant embeds its header and logo directly.

Both declare `XB Niloofar` by system font name, but only `fonts/XB Kayhan Pook.ttf` is bundled. The requested body-font file is absent. Listings configuration also names `LimeGreen` without a direct color-package import in the preamble. These are source-level dependency questions for validation, not observed compiler failures. [Covered source](https://latex.sharif.edu/latex/templates/6398523d2581e80097d08066/zip), [no-cover source](https://latex.sharif.edu/latex/templates/639854882581e80097d08105/zip).

## Course-project report

`Seminar.tex` uses `article`, imports `styles/common.tex` and `styles/custom.tex`, then includes `front/info.tex`, `front/template/title.tex`, `chapters/context.tex`, `bibs/bibs.tex` and `chapters/appendix.tex`. Optional dictionary and religious front-page imports are commented out.

Metadata exposes report title/type, degree, major, group members, course, semester, professor, department and university. The sample chapter demonstrates prose, math, lists, tables, diagrams, algorithms and references. Sample claims and identities must be replaced with actual assignment content.

The preamble loads AMS math, hyperref, PSTricks, graphics/wrapped figures, geometry, euscript, multicol/multirow, caption, algorithmicx/algorithm, localized XePersian and algpseudocode, plus local Persian algorithm vocabulary. The archive has no complete compiler recipe. XeLaTeX plus bibliography processing is an inferred starting point; PSTricks and package ordering require validation.

Bundled assets include a university logo, religious image, PDF diagrams, a PSTricks figure, SVG/draw.io sources, bibliography files, XB Niloofar variants, and XB Kayhan Pook. Active body-font configuration requests system `XBNiloofar`; local file-path configuration is commented out. Digit font `Yas` is requested but absent. A Latin algorithm environment requests Times New Roman. Kayhan is configured with a local path.

Static source concerns, not tested compilation failures:

- Title source references `\EnglishCourseTitle`; no definition was found in the inspected text.
- The `article` document declares theorem counters relative to `chapter` and includes an appendix using a localized chapter command. No compensating chapter-counter definition was found.
- Bibliography selects `ieeetr-fa`, absent from the archive; the supplied `styles/packages/unsrtabbrv.bst` is only a commented alternative.
- Vendored algorithm packages are present under `styles/packages`, while active imports use normal TeX lookup, so the actual loaded version depends on the build environment.

[Report source archive](https://latex.sharif.edu/latex/templates/63b3420c78d656009cf525c7/zip).

## License evidence and attribution

No template-wide license file or explicit reuse/redistribution grant was found in these archives. The report README describes a Persian seminar template and credits Zeinab Seifoori; exercise comments credit the same author. Public download access and attribution do not establish a license.

The coordinating agent also checked the catalogue Details dialogs: they provide description and last-updated information, without an actual license declaration. The report description attributes creation to the TexReady Group, originally for Computer Science students and originally published by TexReady; it says others are welcome. This catalogue attribution should be preserved alongside, rather than substituted for, the archive attribution.

The report has independently attributed third-party files: `algorithm.sty` and `algorithmic.sty` state LGPL version 2 or later; `algorithmicx.sty` and `algpseudocode.sty` have Szasz Janos copyright headers; `unsrtabbrv.bst` carries a copying/modification notice derived from BibTeX styles. These notices do not establish rights for the whole template, fonts, logos, religious image or sample diagrams. Exact embedded font metadata and upstream font licenses were not examined. [Report source](https://latex.sharif.edu/latex/templates/63b3420c78d656009cf525c7/zip).

## Temporary evidence and identity

Investigation root:

`C:\Users\Mahdi\AppData\Local\Temp\sharif-template-review-2a83d6a78de04f438bf0bb6e77d58fe0`

Each subfolder is extracted source, with its corresponding ZIP alongside it. Computed SHA-256 values:

| Archive | SHA-256 |
|---|---|
| `exercise-cover.zip` | `821F758C7998830ED98C1BA2BE5F736A014653D6DF1D13B99026AEC6BB81AA13` |
| `exercise-no-cover.zip` | `BF662C64C76B226AE35C0D9F3AAE992BD5CB717E6FFD6046C642A1AFC67301C0` |
| `course-project-report.zip` | `F408D98D87C8F22A4604DEBC926EEE727A97E650A4F7F6F0B3980C0EA1A30CA9` |

These hashes identify this inspection's bytes, not an upstream release guarantee. Temporary source evidence is not a durable installed template collection.

## Unverified and next decisions

No compilation, rendering, embedding, text extraction, accessibility or visual-quality verification was performed by this source investigation. Catalogue previews are being reviewed separately; they do not establish reproducible output in this runtime.

The coordinating agent subsequently downloaded the original PDFs using the catalogue's visible links and rendered selected pages with Poppler. Visual inspection covered the first page of each exercise variant and the title and first body page of the report. These show the separate exercise cover, compact no-cover exercise header, and report title/body layout respectively. The inspected original PDFs and page images are in `tmp/pdfs/sharif-original-previews/`; they are review evidence, not generated assignment deliverables. [Covered exercise PDF](https://latex.sharif.edu/latex/templates/6398523d2581e80097d08066/pdf), [no-cover exercise PDF](https://latex.sharif.edu/latex/templates/639854882581e80097d08105/pdf), [report PDF](https://latex.sharif.edu/latex/templates/63b3420c78d656009cf525c7/pdf). This preview inspection does not verify local compilation, the remaining report pages, or suitability after student-answer adaptation.

Confirm the initial collection and permitted student-answer adaptations before implementation. Then establish applicable license evidence, configure dependencies, repair source inconsistencies, replace sample content and validate representative PDF outputs. Recording selected template identity/version and source bundles remains a design decision, not implemented behavior.

## Follow-up during implementation

The initial collection, technical repairs, student-answer adaptation, local caching and full source preservation were subsequently approved. See the implementation/acceptance document linked above for the completed behavior; the preceding source risks describe the original ZIPs, not the repaired projects.

Local rendering revealed incorrect Persian shapes and digits with the report archive's modified font, internally named `XB Niloofar Sharif`. Explicit OpenType script settings did not fix it. The preparation recipe now uses the original same-family [XB Niloofar distribution](https://fontlibrary.org/en/font/xb-niloofar), whose publisher page identifies the family/designer and OFL license. The [source ZIP](https://fontlibrary.org/assets/downloads/xb-niloofar/443e92a9b431497a28b6d9e7d1384c40/xb-niloofar.zip) was retrieved and hashed as `3575302c74b55e6992c0a64b7d4a193c0dc8a95fe8ea62d06959ce4586bf90a6`. It contains the regular/bold/italic/bold-italic files and OFL notices; all are cached locally and included in report sources. Correct Persian forms and digits were visually confirmed in the rebuilt samples. Font metadata in the modified archive font also contains an OFL text; this does not supply a template-wide license declaration.
