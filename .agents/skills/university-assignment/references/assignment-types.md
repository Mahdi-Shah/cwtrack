# Assignment types

Read the type off the assignment, not off your assumption. When two types fit, ask — a lab report and an essay look nothing alike in structure even when the topic matches.

At intake, the format comes from the assignment text first: `در قالب Word` → `.docx`, `فایل PDF` → PDF, `حداکثر دو صفحه` → a page budget, `اسلاید پاورپوینت` → slides. **If the assignment says nothing, deliver PDF** via `scripts/render.py`.

---

## ۱. تمرین حل‌مسئله (problem set)

ریاضی، فیزیک، شیمی، مهندسی، آمار. The most common type, and the most dangerous to fake — the answer is checkable, so a wrong derivation is immediately visible.

**Deliver:** problem-by-problem. Setup → given values with units → derivation → result with units → a check on the result.

**Gather:** course slides and textbook chapters the student supplies. Web only to resolve a specific formula or convention.

**Non-negotiable:**
- Every step justified. "با استفاده از رابطهٔ ... نتیجه می‌گیریم" is not a step; show what was substituted.
- Units on every intermediate and final value.
- Show the governing equation with its symbols defined before use.
- If the problem gives data that looks wrong (a missing sign, an implausible magnitude), flag it — do not silently fix it.

**Check before delivering:** substitute the answer back into the original equation. Try a limit (does it reduce to something known?). Try a simple case (set the parameter to zero). Sanity-check the order of magnitude by hand.

**Failure mode:** a confident derivation with one sign error. Re-derive by a second route — dimensional analysis, the special case, or the mirror-image method.

---

## ۲. گزارش آزمایشگاه (lab report)

**The raw data is the student's.** You may compute from it; you may never invent it.

**Deliver:** هدف → مبانی نظری → دستگاه و مواد → روش کار → داده‌های آزمایش → محاسبات و تحلیل خطا → نتیجه‌گیری → منابع (فقط اگر خواسته شده) → پیوست (داده‌های خام).

**Error analysis is the part that earns marks.** Not optional, and not "خطای اندازه‌گیری" as a sentence:
- Propagate the instrument uncertainty into the final result: `Δk/k = Δ(Δx)/Δx`
- Distinguish random (repeat and average) from systematic (calibration, zero offset) error
- Compare against the theoretical value and say whether the gap is inside your error budget

**Every placeholder in the raw-data table must be visible** — use `[نیازمند داده]`, and list what the student must measure in the delivery note. A table of invented numbers is the worst thing this skill can produce.

**If the student has no data yet:** deliver the whole report as a template with every data cell marked, plus the equations they need to fill in and what range of values to expect. Do not fabricate numbers "as an example" without labelling them unmistakably.

---

## ۳. مقاله و تحلیل (essay / analytical paper)

**Deliver:** a claim, then the argument for it, then the counterargument, then what would change your mind.

**Structure:** صورت مسئله → ادعای اصلی → شواهد → مخالفت‌ها → محدودیت‌ها → نتیجه‌گیری. Follow the course's required structure when it names one.

**Gather:** the readings the course assigned are the spine. Web sources extend, not replace, them. 5–8 solid sources beats 30 scraped ones.

**Rules:**
- Write the thesis sentence first. If you cannot write it in one sentence, the paper has no argument yet.
- Quote sparingly and verbatim, with a page or paragraph anchor in your working notes.
- If the assignment does not ask for references, do not print a bibliography — but keep the source ledger in the brief so every claim remains traceable to you. See `../SKILL.md` on why.
- Every factual claim outside your own reasoning needs a source you retrieved. Paragraphs of unsourced assertion are the classic failure.

---

## ۴. مرور ادبیات (literature review)

**Deliver:** not a list of summaries. Group the sources by *position*, not by author.

**Structure:** دامنه و روش جست‌وجو (what you searched, where, up to when) → طبقه‌بندی رویکردها → تحلیل هر خوشه → نقاط اجماع و اختلاف → شکاف پژوهشی → نتیجه‌گیری.

**Rules:**
- Say what you searched and what you excluded. A review whose method is invisible cannot be trusted.
- Date every source. A field where the newest work is three years old is a field worth flagging.
- The synthesis section is the deliverable. If the draft reads like an annotated bibliography, it is unfinished.
- Do not claim a field "has not studied X" without a search that supports it, or write `[نیازمند منبع]` instead.

---

## ۵. سمینار و ارائه (presentation)

**Deliver:** slides, and a separate script. Never the same text twice.

**Slide discipline:** one idea per slide, ~5–7 words of headline, the body in the talk not the slide. `render.py` produces a document, not slides — for slides, use PowerPoint via python-pptx or the `pptx` skill if installed, and check it renders before delivering.

**Always include:** a closing slide with the two or three sources that actually carry the argument, and a slide of open questions if the student will be asked.

**Timing:** ask how many minutes. 1 minute per slide is the safe default.

---

## ۶. پروژهٔ کدنویسی (code project)

**Deliver:** working code that runs, plus a short README. Not a code dump.

**Rules:**
- Run it. Paste the actual output. If it does not run, say so and do not claim it does.
- Include the test or at least a usage example with expected output.
- Name the language, the version, and the dependencies, and pin them.
- If the assignment specifies a required algorithm or data structure, state where it is used. Proving a requirement is met is part of the answer.
- Comments and explanation in Persian; identifiers in English.

---

## ۷. اثبات و استدلال کیفی (proofs)

**Deliver:** the proof, and after it a one-line note on the key idea that made it work — that is what gets remembered.

**Rules:**
- State the proposition precisely, including every hypothesis. A proof of a mis-stated theorem is worthless.
- Do not skip the step you yourself found hard. That is exactly the step the student will get stuck on.
- Say which step needs a result beyond the course's scope if it does, or supply a lemma.
- Check the base cases and the edge cases (empty set, zero denominators) explicitly.

---

## ۸. ترجمه

**Deliver:** the translation, plus a short note on every terminological choice that a translator would argue about.

**Rules:** keep the register and formatting of the original. Keep proper nouns in the convention the field uses. Flag an ambiguity instead of silently choosing — the student may need to know.

---

## ۹. پروژهٔ طراحی و مهندسی

**Deliver:** the design with its assumptions and constraints explicit, the governing calculations, and the failure modes.

**Rules:** every dimension traced to a code clause or a standard — `[نیازمند منبع]` if you cannot find it. Show the load path and name the governing (worst) case. Include a tolerancing note if it is dimensioned work. A drawing must be produced by a script and embedded, never described.

---

## When the type is unclear

Ask one question with two or three concrete options, and say what you would do with each answer. Do not stall on ambiguity you can resolve — resolve it, state the assumption, and note it in the delivery.
