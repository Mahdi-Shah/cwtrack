# Persian output rules

The deliverable is Persian academic prose rendered to PDF. This file is the house style; follow it unless the course specifies otherwise.

## Script and direction

- Body is RTL. Latin technical terms stay Latin and are set LTR inside the RTL flow.
- The PDF is set in Vazirmatn, embedded from `assets/fonts/` — no install needed, and the output is identical on any machine. Fallback faces (Tahoma, Segoe UI) were not designed for Arabic script; if you pass `--font system` you will see worse kerning.
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
