# Changelog

All notable changes to this project. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] — 2026-10-05

First public release.

### The tool

- `cwtrack fetch` — logs in through the browser form, saves the assignment page for
  every course, writes the store. The site's image captcha is saved and read by a
  human; there is no automated solver and there will not be one.
- `cwtrack ui` — a self-contained dashboard with the Persian UI font embedded as a
  data URI. Leads with what is left, then a 30-day timeline, then counts, then one
  collapsible card per course. Countdowns refresh every 30 seconds.
- `cwtrack gaps` / `open` / `report` — outstanding work, worst first; the short list;
  the full Persian markdown report.
- `cwtrack brief` — creates a working folder for one assignment, pre-filled with
  everything the site knows. This is the seam to the `university-assignment` skill.
- `cwtrack material --course N` — prints and indexes a course's material folder.
- `-o` works on every text-producing command, because Persian output is mangled by a
  stock Windows console.
- A missing store raises instead of reporting zeros, and an unrecognised status lands
  in `unknown` and is called out. Neither can quietly read as good news.

### Both skills

- `sharif-cw` — tracks assignments on cw.sharif.ir.
- `university-assignment` — takes an assignment and produces a Persian PDF. Strict
  mode: nothing is stated that was not retrieved or computed, gaps are marked
  `[نیازمند داده]` / `[نیازمند منبع]` / `[حل نشد]`, and the delivery note lists
  everything unverified.

### Correctness

- Jalali conversion validated as properties over 1380–1442: Nowruz on 20 or 21 March,
  year length 365 or 366, exactly 8 leap years per 33-year cycle, every day of a
  year consecutive, and both conversion paths agreeing. Prefers `jdatetime` when
  installed; otherwise uses an embedded table and returns nothing outside its range.
- Submission-state precedence tested as a whole, because `"not submitted"` contains
  `"submitted"` and a draft is not a submission.

### Bugs found by the tests

- `fetch` passed the wrong argument count to the login call on a fresh session, so
  it prompted for a password and then died with `TypeError`.
- An English table header did not map the name column, so every row came out
  nameless.
- A Persian decimal separator in the grade column (`۱۹٫۵`) read as "not a grade",
  dropping a real mark.
- `_grade_score(None)` raised instead of returning `None`.
- The same assignment appearing on both the overview page and the assignment page
  was counted twice — de-duplication was per page rather than per dump.
- The dashboard font resolver pointed one directory above the package and found
  nothing, degrading to Tahoma silently.

### Known limitations

- Verified against cw.sharif.ir only. The Moodle structure is generic; the theme,
  the Jalali deadlines, the captcha plugin and the four-column table are not.
- English filenames match loosely: `HW4_Oscillator.pdf` does not match
  `Homework 4 — Oscillator`. Persian filenames fold correctly.
- Course material is a folder convention, not an automatic download — the page markup
  needed to write a correct downloader has not been observed.