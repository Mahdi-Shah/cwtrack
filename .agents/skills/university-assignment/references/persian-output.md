# Persian output rules

The deliverable is Persian academic prose rendered to PDF. This file is the house style; follow it unless the course specifies otherwise.

## 0. When a template exists, the template wins

**This overrides every other rule in this file.** If the course supplies a form, template, or
`docx`/`pptx` skeleton, fill *that file* rather than authoring a new document. The lecturer's own
layout, fonts, wording and table geometry are the spec; changing them is a defect, not an improvement.

Before writing anything into a supplied template, measure it:

- **Fonts.** Read `w:rFonts/@w:cs` (the complex-script slot — the one that governs Persian in
  Word), `w:ascii` and `w:hAnsi`. `w:cs` is the one that matters; a document whose Persian renders
  in the wrong face almost always has `w:cs` unset and only `w:ascii` set. Read the sizes per role:
  body, table header, table cell, heading. A `Normal` style of `DejaVu Sans` does **not** mean the
  body is DejaVu — runs usually override it with `B Nazanin` or whatever the course uses.
- **Sizes per role**, then reuse them exactly. Do not shrink text to fit a cell. Cells grow.
- **Fill in place.** Set `cell.text`, then apply the font to the run you create. Setting a cell's
  text and then styling the paragraph is not enough — the run needs its own `w:rFonts`.

A mismatch is the single most visible tell that a document was not made by the person whose name is
on it, and it is entirely avoidable. Never ship a document whose body font differs from the rest.

To reproduce a template faithfully in PDF, write the HTML by hand with an explicit
`font-family: '<the course face>', …` stack. Do not assume `render.py`'s bundled Vazirmatn is
appropriate here — it is the house face for documents you author from scratch, and the *wrong*
choice when a course template is in play.

## 0.b The document must stand alone

The deliverable goes straight to a lecturer. Therefore:

- **No instructional residue.** No `[نیازمند داده]`, `[همین را نگاه کن]`, `[حل نشد]`, "پر کنید",
  "این بخش را حذف کنید", TODO markers, or bracketed anything, inside the delivered file. Those go
  in the delivery note or the brief, never on the page.
- **No meta-commentary.** Do not write "همان‌طور که در سطر تعمیرپذیری نوشتم", "این نکته را خودم
  اضافه کردم", or any reference to the writing process, to a previous section as a cross-check, or
  to the student as an audience. The lecturer did not ask how you worked; they asked what you found.
- **No appendix of guidance** inside the submitted file. Teaching notes go in a separate document.
- **Address the lecturer, not the student.** No second person aimed at the student inside the prose.

If a cell cannot be filled truthfully, choose the honest sentence that *is* available, deliver the
document, and put the gap in the delivery note. An incomplete but clean page beats a complete page
that reads like a worksheet.

## 0.c Voice

Write the way a competent student writes, not the way a textbook writes.

- **Vary the sentence shape.** Do not open all ten cells with the same construction. If three
  consecutive cells begin «این یعنی…» or «که…»، rewrite two of them.
- **Do not restate the criterion.** The table's first column already says `تعمیرپذیری`. Writing
  "از نظر تعمیرپذیری نقطه قوت است" in every row is padding, and repetitive symmetry across rows
  reads as machine-generated. Let the reasoning imply the criterion.
- **Avoid tic phrases** that flag machine prose in Persian academic writing: `بی‌تردید`,
  `به‌روشنی`, `در نهایت`, `شایان ذکر است`, `می‌توان گفت` used as a filler opener, and stacked
  triples of near-synonyms.
- **First person is allowed and often better** — «به نظر من …», «من این را نقطه قوت می‌دانم».
  A student writing an opinion naturally uses it; its absence reads as impersonal machine text.
- **Concrete over abstract.** `کف محفظه پلاستیکی است و بعد از چند سال ترک می‌خورد` beats
  `نشانه‌هایی از فرسودگی مشاهده شد`. Name the part, name the material, name the direction.
- Do not use the ZWNJ-heavy compound chains as an end in themselves; the compounds in `## ZWNJ`
  below exist to be *correct*, not to be dense.

## 0.d Never write tashkeel. Ever.

**No vowel marks in any deliverable, without exception.** Not fatha, not kasra, not damma, not
tanween, not shadda, not sukun, not superscript alef — and no hamza-above (``) on a bare
`ه`. Also no tatweel (`ـ`) for stretching.

```
وسیلهٔ      ✗     وسیله‌       ✓
می‌شود      ✓     نموده‌ای     ✓
مُهندسی     ✗     مهندسی      ✓
```

Why this is a hard rule rather than a style preference: ordinary Persian writing, including
undergraduate engineering coursework, carries **zero** diacritics. Persian has lost its short vowels
in speech centuries ago, so a student types `مهندسی`, not `مهندسی`. Text that is systematically
vowelled reads as machine-generated before its content is read, and it is the single loudest tell in
the whole document — louder than vocabulary or sentence shape.

The traps that reintroduce it silently:

- Word processors and `render.py` will not add them, but a copied passage may already carry them.
  Transcribing a lecturer's boilerplate by hand can quietly add a `` that was not in the original.
- Spell-checking and "improved Persian" text copied from the web arrives vouched.
- **Strip before delivery, not by eye.** Scan the finished file:

  ```python
  COMBINING = re.compile("[ً-ٰٕۖ-ۭ]")   # tanween..superscript alef, quranic marks
  text = COMBINING.sub("", text)                 # apply to YOUR prose
  assert not COMBINING.search(text)              # and assert it
  ```

  Run that over the delivered artifact — the `.docx` runs and the extracted PDF text, not the source
  string. `hamza-above` is inside that class, so «وسیله» is caught by the same pattern.

  If the course's own template contains marks, leave the template's boilerplate alone and strip only
  what you wrote — but check whether the original really has them before assuming, and report what
  you found rather than silently "fixing" the lecturer's file.

## 0.e Punctuation effort is proportional to the document

Do **not** apply typographic standards the course is not asking for. A student solving a coursework
problem set does not punctuate carefully, and a carefully punctuated student submission is its own
tell.

| Document | Punctuation |
| --- | --- |
| Problem set, form, worksheet, lab report, short homework, observation sheet | **Do not fuss.** End sentences with `.`. Use `،` only where the sentence would otherwise be genuinely unreadable. Avoid `؛`, `:` in prose, `—`, `«»` for ordinary emphasis. |
| Essay, report, seminar paper | Ordinary Persian punctuation: `،` `.` and `؟` |
| Research article, journal submission | Full formal Persian punctuation, and only here |

The trap: defaulting to the tidy prose register — semicolons, colons, em dashes, parallel triads —
and producing something a student did not write. When in doubt for a simple assignment, write the
plainer version. **Under-punctuated is invisible; over-punctuated is a signature.**

ZWNJ is not punctuation and is separate: it is a spelling correctness issue (see below), so apply it
regardless of document type.

## Script and direction

- Body is RTL. Latin technical terms stay Latin and are set LTR inside the RTL flow.
- The PDF is set in Vazirmatn, embedded from `assets/fonts/` — no install needed, and the output is identical on any machine. Fallback faces (Tahoma, Segoe UI) were not designed for Arabic script; if you pass `--font system` you will see worse kerning.
  **This applies only to a document you author from scratch.** If the course supplies a template,
  use that template's face — see `## 0`.
- First occurrence of a foreign term: `ترمودینامیک (thermodynamics)` — after that, Persian is enough.
- Prefer the established Persian academic equivalent when one exists. If not, keep the Latin term; do not coin a transliteration that a professor would not recognise.

## Numbers and digits

`render.py` converts standalone ASCII digits to Persian and leaves identifiers Latin. So write the number, not the digit shape, and let the renderer decide:

| Write | Get |
| --- | --- |
| `12` | `۱۲` |
| `1404` | `۱۴۰۴` |
| `5%` | `۵٪` |
| `12-15` | `۱۲-۱۵` |
| `COVID-19` | `COVID-19` (kept) |
| `ISO-8601` | `ISO-8601` (kept) |
| `3.14.7` | `3.14.7` (kept — dotted version) |

Use `--digits latin` for a document that is mostly Latin (identifiers, code, chemistry).

Decimal separator is `٫` (U+066B), not `.`. Thousand separator in prose is `٬` (U+066C). `render.py` does not rewrite separators — write them yourself when a number is Persian-typed already, and keep ASCII when it is Latin.

## ZWNJ (نیم‌فاصله)

Use U+200C in these and similar compounds. Most word processors get this wrong, so it is worth being deliberate:

- `می‌شود` `نمی‌شود` `بوده‌اند` `کرده‌اند`
- `نمی‌توان` `نمی‌دانم` `نمی‌گوید`
- `به‌طور` `به‌کار` `به‌شرط` `هم‌زمان` `هم‌بش`
- Names with prefixes: `می‌دانم`, `بهره‌وری`, `(handler)` stays Latin
- `۱۴۰۴/۰۵/۱۲` — keep `/` inside Persian dates as an ASCII slash between Persian digits; it reads better than `٫`

Do not use a regular space where ZWNJ belongs, and do not use ZWNJ where the words are genuinely separate.

## Punctuation

Applies to essays and research writing only. For a problem set or a form, see `## 0.e` and do less
than what follows.

- Persian comma `،` (U+060C) — not the Latin comma.
- Persian full stop `。` is not used; end Persian sentences with `.`
- Semicolon `؛` (U+061B), question mark `؟` (U+061F) — the Persian forms.
- Colon `:` and parentheses `()` are shared; in an RTL line parentheses around Latin text render correctly on their own.
- Never end a Persian sentence with a Latin `.` followed by a Latin letter.

## Units and symbols

- SI symbols are Latin and take a space from the number: `۱۲ m` not `۱۲m` — but the space should be a thin one. Write `12 m` and let the renderer digit-convert.
- Do not Persianise unit symbols. `N`, `m/s`, `kg·m⁻²`, `°C` stay as-is.
- Keep exponents Unicode where practical (`²`, `³`, `⁻¹`) so they survive without a TeX engine.

## Formulas — the important one

There is **no TeX engine** in the PDF pipeline. `$...$` and `\(...\)` are unwrapped and printed verbatim in an isolated LTR span; they are not typeset. So:

- Write formulas **Unicode-first**, so they read correctly as plain text: `F = k·Δx`, `∫₀^∞ e^(-x²) dx`, `∂u/∂t = α∇²u`, `Σᵢ xᵢ²`
- Reach for `$$...$$` only for genuinely multi-line layout, and then keep it to display-identifiers like `\frac{a}{b}` and `\begin{aligned}`
- Put units in the text next to the symbol, not inside the formula
- If the course needs real typeset math, that is the LaTeX path — see below, and ask before switching

## Layout

- Headings numbered by the course's own convention (`۱.` `۱-۱.` `۴.۲.۱`), not invented
- Table captions above the table, figure captions below
- Long tables must fit A4 — if a table has more than ~7 columns, split it or transpose it
- Any figure you draw must be generated with a script, saved as PNG or SVG, and embedded with `![caption](path)`. Never describe a figure you did not produce.

## When the course wants LaTeX instead

`xelatex` is available (MiKTeX). The `xepersian` route needs the Persian font stack set up and the first run triggers MiKTeX package installs, which can stall. Raise it with the student first, and expect one setup round-trip; `render.py` plus Markdown is the reliable default.
