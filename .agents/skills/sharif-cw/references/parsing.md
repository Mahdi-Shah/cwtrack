# Parsing the saved pages

Everything `cwtrack` knows about cw.sharif.ir's HTML, in one place, so it can be corrected when the theme changes.

## The pipeline

```
fetch  ->  .cw/dump/_my_courses.html
           .cw/dump/_dashboard.html
           .cw/dump/course_<id>.html        one /mod/assign/index.php per course
report ->  reads the dump, never the network
```

Splitting fetch from report is deliberate. The parsers below are written against Moodle's structure but have not been run against this theme's real HTML, so the first `fetch` is what they get checked against. `cwtrack raw` lists the dump.

## Course discovery

`/my/courses.php`, matching `course/view.php?id=(\d+)`. Id `1` is dropped — it is the site home pseudo-course, not a course with assignments.

Failure mode: if the layout changes, no ids are found and `fetch` stops with a clear error rather than reporting "0 courses". An empty result is never silently treated as "you have no assignments".

## Row extraction

A row is a `<tr>` containing a `mod/assign/view.php?id=N` link. That link is the anchor — it is what makes a row an assignment row, and it is why the Grade-book row in the same table is correctly ignored.

From each row:

1. **Name** — the text inside the first `<a>`, rather than the first cell. On some themes the first cell carries layout markup that would otherwise win.
2. **Deadline** — the first cell that `parse_due` can turn into an epoch. If none parses, the first non-empty cell is used for display and the epoch stays `None`.
3. **Status** — the remaining cell with the highest `_status_score`, i.e. the most status keywords.
4. **Grade** — a remaining cell that `_grade_score` accepts as a number.

Picking status and grade by content rather than by column index is what survives a theme that reorders columns or inserts a new one.

## Status keywords

Matched case-insensitively, Persian and English, because the site ships both.

| group | words |
| --- | --- |
| submitted | `submitted`, `ارسال شده`, `ارسال‌شده`, `تحویل شده`, `sent for marking`, `sent for grading` |
| not submitted | `not submitted`, `no submission`, `none`, `ارسال نشده`, `ارسال‌نشده`, `بدون ارسال`, `نامشخص` |
| draft | `draft`, `پیش‌نویس`, `پیش نویس` |
| closed | `closed`, `بسته`, `بسته شده`, `پایان یافته` |
| graded | `graded`, `نمره داده`, `تصحیح شده` |

## Classification precedence, and why it is that order

```
graded word  -> graded
closed       -> closed
draft        -> draft
not submitted -> overdue (if past deadline) else open
numeric grade -> graded
submitted    -> submitted
past deadline -> overdue
otherwise    -> unknown
```

Two of these lines exist because of traps, and reordering them silently breaks the tool:

**`not submitted` is tested before `submitted`, because `"not submitted"` contains `"submitted"`.** This is not a theoretical concern — the first version of this script joined every cell into one string, tested `submitted` first, and cheerfully reported four out of four undone assignments as handed in. It is precisely the failure this tool exists to catch.

**`draft` is tested before the numeric grade.** A draft is not a submission. A row reading `Draft` with a stray number in the grade column must not be reported as done.

**`unknown` is the default, never `submitted`.** An unrecognised status is a parsing problem, and it goes in the report's "go look at this" section rather than quietly counting as finished.

## Jalali dates

The site renders Persian dates. Three shapes show up:

```
شنبه ۲۱ مهر ۱۴۰۴، ۲۳:۵۹      Persian month name + Persian digits + clock
۱۴۰۴/۰۸/۱۴، ۲۳:۵۹              Persian digits, numeric separators
2026-11-20, 23:59              Gregorian, English UI
```

Parsing order:

1. Fold Persian and Arabic digits to ASCII. Split on `،`/`,` and keep only the left part — **otherwise the clock hands the year parser a `59`.** That was a real bug here.
2. `YYYY[-/.]MM[-/.]DD`. A year below 1700 is Jalali and gets converted; 1700 and up can only be Gregorian.
3. `YYYY-MM-DDTHH:MM`.
4. Persian month name, matched on token boundaries — Persian letters are `\w` under Python's Unicode regex, so `\b` is what stops `دی` matching inside `دیگر`.

Anything unparsed returns `(raw_text, None)`. The raw text is always printed in the report, so a student sees the site's own wording and never has to trust our arithmetic over it.

### Why `jdatetime` and not a formula

Conversion is done by `jdatetime` when installed, and by an embedded Nowruz table when not. It is emphatically **not** done by one of the short "33-year formula" conversions that circulate on GitHub: two hand-rolled attempts in this script were wrong, placing Nowruz on 22 March and producing 364- and 367-day years.

The embedded table (`NOWRUZ`, Jalali 1380-1442 = 2001-03-21 .. 2063-03-21) was generated from `jdatetime`, diffed against it entry by entry, and validated on four invariants:

- Nowruz falls on 20 or 21 March across the whole range
- Year length is only ever 365 or 366
- Exactly 8 leap years per 33-year cycle
- Every day of a year maps to consecutive Gregorian days, and the two paths agree on every day of a three-year span

It runs two years past its last usable year so the final year's Esfand is still derivable — Esfand is the only month whose length needs the leap flag, which is the only reason `cwtrack` computes it.

If `jdatetime` is present the table is not consulted, and `pip install jdatetime` is the only setup this tool ever needs. It is not required.

## Timezone

Deadlines are rendered in the user's configured timezone. `SITE_TZ_OFFSET` assumes Asia/Tehran (UTC+03:30, no DST since 2022). That only decides which side of "days remaining" a deadline falls on, and the site's own date text is printed next to every row, so the consequence of being wrong is cosmetic.

## Epoch arithmetic

`datetime(...).timestamp()` routes through the OS `mktime`, which on Windows raises `OSError 22` for Jalali-era years — a hard crash on exactly the dates this site prints. `_epoch()` uses `date` subtraction instead: no syscall, no tz database, no failure.

## The local-file matcher

`_norm()` folds ZWNJ, harakat, `ک→ك`, `ی→ي`, and Persian/Arabic digits to ASCII, then takes the token set. Two shared tokens is the match threshold.

Reliable for Persian filenames, unreliable for English abbreviations: `HW4_Oscillator` shares one token with `Homework 4 — Oscillator`, not two. Lowering the threshold to one produces false positives — a course named `Digital Circuits` matches every file containing "circuits". Leave it at two and read the misses by eye.
