# Changelog

All notable changes to this project. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/).

## [Unreleased]

### The skills are now the interface

The project was already two skills and a CLI, but the skill OpenCode actually loaded
was a stale copy that had drifted until it no longer had a `brief` command — the seam
between the two skills. A skill-driven session therefore had no way to hand work over,
and `brief` was never mentioned to the user. Three changes close that:

- **`cwtrack.api`** — a surface a skill calls. It returns Python values and never
  prints, prompts, or opens a browser; each of those three made a skill fail in
  practice, and each now has a test. `status`, `outstanding`, `gaps_text`,
  `open_text`, `report_text`, `build_dashboard`, `materials_text`, `make_brief`,
  `ingest`, `refresh`, `paths`.
- **The CLI calls the same API**, so the command line and the skills cannot disagree
  about what is outstanding. It keeps the three things the API refuses: prompting,
  opening the dashboard, and `-o` for a console that cannot show Persian.
- **`tools/link_skills.py`** points the installed skills at `.agents/skills/` with a
  file link, and `--check` fails the suite when they have diverged. An installed copy
  is a fork, and this one already was.

### The captcha handshake

`auth.do_login` called `input()`, so from a shell with no terminal a fetch could not
complete at all — it raised EOFError and suggested setting an environment variable.
Login is now two calls: `auth.submit()` returns `captcha_required` with the image, and
the caller hands back the answer. The CLI prompts; a skill shows the image.

`api.refresh()` also writes `captcha-zoom.html`, the same image at 4×. The site's is
about 190×40 px, which is hard enough to read that a miss costs a whole round trip.

### Optional captcha OCR

A measured, gated attempt to read the login captcha before asking the user. Off unless
both the `ocr` extra and a `tesseract` binary are present; `CW_OCR=0` disables it
explicitly. The default path — a human reading a zoomed image — is unchanged and
remains the fallback for every uncertain case.

The submission bar is set by measurement, not optimism. On 20 generated samples in the
plugin's style:

| | |
|---|---|
| best single strategy (crop to the ink) | 14/20 |
| upscale 4× first | 13/20 — worse than not resampling |
| five-strategy ensemble | 13/20 |
| auto-submit at ≥70% agreement | 5 submitted, 5 right, 0 wrong |
| auto-submit at ≥50% agreement | 9 submitted, 8 right, 1 wrong |

So the gate is 70% agreement across five readings, which automates about a quarter of
logins and never submits a wrong answer. Three findings shaped it, all counter to the
usual advice:

- `--psm 7` — the textbook single-line mode — reads *nothing* here. The plugin's curved
  strokes defeat its baseline estimate; psm 8 (a single word) is the right model for a
  short token, and it is tried first.
- Upscaling hurt. Cropping to the ink bounding box is what helps.
- tesseract's confidence is not a usable gate. Correct readings came back at 0.0 and a
  wrong one at 48, so a threshold discards right answers without ever proving one.
  Agreement between strategies is the signal instead.

Also found while measuring:

- Restricting tesseract to an uppercase-only whitelist made it read a lowercase `b` as
  `D` — a silent, confident, wrong answer. Both cases are allowed now and the folding
  happens in Python.
- The `stdout` renderer reports no confidence at all in this build, so a parser reading
  stderr gets 0.0 for every reading; the `tsv` renderer is used instead.
- Comparing a best-so-far against an initial 0.0 with `>` recorded no reading at all,
  which reported perfect reads as "no reading".

Bounds, because an unbounded loop against a login endpoint is the failure this feature
could inflict: one engine attempt per login, never one per image, and three human
attempts before it stops.

### Correctness

- **`counts.done` counted an unrecognised status as finished.** It was
  `total - open`, and `unknown` is deliberately not an open bucket, so the one state
  the tool refuses to interpret was reported as handed in — the exact failure the
  `unknown` bucket exists to prevent, sitting in the headline number rather than in a
  detail. `done` is now the named states, `unknown` is counted separately, and the
  total agrees with the per-course figures, which already used the correct definition.
  Found by a test written for the API, checking the documented rule against the code.
- `auth.submit()` reports a rejected captcha with a freshly downloaded image, because
  Moodle invalidates the previous one; re-showing the spent image cannot succeed.
- Credentials are checked before the HTTP client is built, so a call without them
  cannot open a socket.

### Testing

- `tests/test_api.py` — 36 tests for the skill-facing surface: it never prompts (checked
  by patching `input`, and statically by parsing the module so the docstring explaining
  the rule does not read as a violation), never prints, never opens a browser, and
  never reports more than the store holds.
- A guard that a skill is not installed as a copy, and that every `api.*` call and
  every module the skill names actually exists.
- The "every command in the skill is real" guard now matches whole command lines. It
  read `from cwtrack import api` as a subcommand named `import`, and there is now a
  second test asserting it still matches the commands around it, so a rewrite cannot
  quietly turn it into a no-op.
- `tests/test_captcha.py` and `tests/test_captcha_login.py` — 37 tests. The vote, the
  gate, the charset filter that never invents a character, the one-attempt cap, and
  the guarantee that `CW_OCR=0` or a missing engine leaves the human path untouched.
  No test needs tesseract: the engine is stubbed and the sample images are generated.
  The one test that measures against the real engine skips when it is absent, because
  the unit tests are the contract and that one is the evidence.

353 pass, ruff clean.

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