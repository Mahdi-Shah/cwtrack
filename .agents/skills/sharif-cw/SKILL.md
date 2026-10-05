---
name: sharif-cw
description: 'Tracks the user''s own courses on the Sharif courseware site at cw.sharif.ir: fetches assignments, submission status, deadlines and grades into a local store, keeps each course''s material folder indexed, renders a single-page dashboard, reports what is still outstanding, and creates a working brief that hands over to the university-assignment skill. Use when the user asks which assignments are outstanding, what is due, what is late, what they already handed in, asks to start or solve work on an assignment, or wants a dashboard of their courses — "تکالیفم را بررسی کن", "چیزی از قلم افتاده؟", "کدام تکلیف تحویل نشده", "مهلت‌ها کی است", "یه داشبورد از درس‌هام بساز", "برای این تکلیف بریف بساز", "تکلیفمو حل کن". The user speaks; you call the API. The only thing asked of a human is reading the login captcha.'
---

# Sharif courseware (cw.sharif.ir)

Answers one question properly: **what have I not handed in yet, and how late am I?**

The user asks in a sentence. You call `cwtrack.api`. You do not ask them to run
anything, and you do not read a command's stdout to find out what is due.

## Call the API, do not run the CLI

```
src/cwtrack/
├── api.py        <- what you call. returns Python values. never prints.
├── paths.py      where the store, dump and work folder are
├── auth.py       login, and the captcha handshake
├── client.py     HTTP, cookies, retry
├── fetch.py      downloading pages
├── dates.py      Jalali/Gregorian, relative deadlines   <- pure, no I/O
├── parse.py      HTML -> assignment rows
├── classify.py   submission state -> verdict
├── match.py      finding unsent work on disk
├── tracker.py    the on-disk store
├── report.py     Persian markdown
├── dashboard.py  the HTML
├── brief.py      the handoff to university-assignment
└── cli.py        argparse, for a human at a terminal
```

Every function returns data and never prompts, prints, or opens a browser. That is
deliberate — see "Why the API is shaped this way".

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -c "import json; from cwtrack import api; print(json.dumps(api.status(), ensure_ascii=False, indent=2, default=str))"
```

**Set `PYTHONIOENCODING` first, every time.** A stock Windows console is cp1252 and
has no Persian letters, so without it you get `UnicodeEncodeError` or `???` and will
conclude — wrongly — that the data is empty. If you prefer a file, write with
`encoding="utf-8"` and read that; but a `Get-Content` without `-Encoding UTF8` has the
same defect one step later.

### What you call

| Call | Gives you |
| --- | --- |
| `api.status()` | counts, `urgent`, `soon`, `unscheduled`, `unknown`, per-course, store paths |
| `api.outstanding(days=None)` | open work, soonest first, each with `cmid` and `remaining` |
| `api.gaps_text()` | the one-screen Persian answer |
| `api.open_text(days, local)` | markdown table of what is still owed |
| `api.report_text(local)` | the full Persian report |
| `api.build_dashboard()` | path to the HTML; **does not open it** |
| `api.materials_text(course)` | a course's material folder and its contents |
| `api.make_brief(cmid, force)` | the working folder; may return `needs_choice` |
| `api.refresh(captcha=...)` | the network step; see the handshake |
| `api.paths()` | store, dump and work folder |

Pass `local=<folder>` to `open_text` or `report_text` to flag work that exists on
disk but was never uploaded. It is a lead, not a conclusion — report it as "this file
looks like it may be the one", never as "you have already done this".

### Handle the return values, do not assume

- `api.make_brief()` returns `{"status": "needs_choice", "candidates": [...]}` when
  more than one item is open. **Ask which one.** Two assignments due the same
  afternoon are not the same problem.
- It returns `{"status": "nothing_outstanding"}` when nothing is open.
- A missing store raises `CwError`. Report that as "I could not find your data", not
  as "you have nothing due" — see the rules.

## The flow

### 1. Refresh, if the data is stale

`api.status()["refreshed"]` says how old the submission statuses are. Countdowns are
computed live and are always current; statuses are not. Refresh when it is older than
today, or when the user asks for the current picture.

### 2. Answer from `status()`

**Lead with what is overdue, then what is due soon. The full list is supporting
detail, not the point.** Say what is left, in how long, and what it is — not "you have
2 open items in 1 course".

### 3. Hand over to `university-assignment`

When the user wants to actually *do* something outstanding:

```python
api.make_brief(cmid=<id>)   # or ask, if it returns needs_choice
```

That writes:

```
work/<course>/<assignment>/
├── brief.md      everything the site knows, and what it does not
├── HANDOFF.md    what to do next, in order
├── draft.md      where the answer goes
└── source/       course material
```

Then run the **`university-assignment` skill on that folder**. Its `brief.md` section ۲
(the assignment text) is deliberately empty because the site does not expose it — fill
it in from the assignment page or the lecturer's material before solving. Do not solve
a brief whose section ۲ is still empty: that is solving the wrong question
confidently.

`make_brief` will not overwrite an existing folder without `force=True`, because
sections 2 to 7 are the user's own writing. Report that rather than forcing it.

## The captcha — the one thing a human does

`api.refresh()` logs in and downloads. cw.sharif.ir puts an image captcha
(`local_logincaptcha`) on the login form, so the first call returns:

```python
{"status": "captcha_required", "image": Path, "viewer": Path, ...}
```

1. Show `viewer` to the user — it is the captcha at 4×, because the site's own image
   is about 190×40 px and genuinely hard to read. Use the preview/preview-file tool on
   that path. Showing `image` directly wastes round trips.
2. Ask what it says.
3. Call `api.refresh(captcha="<their answer>")`.

If it comes back `captcha_rejected`, a **new** image was already downloaded in the
response — show that `viewer` and try again. Do not restart from scratch.

**You will usually not get this far.** `api.refresh()` tries to read the captcha itself
before it asks you, when tesseract and the `ocr` extra are installed. It reads the
image five ways and submits only when at least 70% of the readings agree; measured on
20 generated samples that automated 5 of 20 logins and got all 5 right. Otherwise it
returns `captcha_required` exactly as above and you show the image.

When it does try, the state tells you what happened:

| `result["status"]` | `result["ocr"]` | What to do |
| --- | --- | --- |
| `ok` | absent | It worked. Say so and carry on. |
| `captcha_rejected` | `{reason: "rejected_by_site", ...}` | It read it confidently and was wrong. Show the new `viewer` and ask the user. Say the reading failed — otherwise a wrong guess looks like a wrong password. |
| `captcha_required` | `{reason: "low_agreement", ...}` | The readings disagreed. Show `viewer`, and mention the tentative reading in `ocr["read"]` so the user can check it quickly. |

The engine gets **one attempt per login**, never one per image. If it has already been
used, `ocr` is absent and the user answers every remaining round. Up to three human
attempts are made, then it stops — after that they are squinting, not solving.

`CW_OCR=0` turns it off completely. Nothing above changes; the image is simply shown
from the start.

`captcha_rejected` after two or three good reads usually means it is not the captcha
any more. Check whether the password was reset via *forgot password*; cw.sharif.ir
currently asks every user to do that, and it looks exactly like a credentials failure.

`{"status": "needs_credentials"}` means `CW_USER` and `CW_PASS` are not set in the
environment. Ask the user to set them, or offer to take a username and password as
arguments. Never put a password in a command line — argv lands in shell history.

### Where the line is

The owner has decided the OCR goes in, on the record, and it is shipped as a measured
and gated convenience rather than a silent override. What that means for you:

- **Do not improve it.** No better preprocessing, no higher-agreement mode, no
  retry-until-it-works. The 70% gate is where the accuracy stops being free; raising it
  buys a higher submit rate by submitting wrong answers, and the whole point of the
  measurement was that it does not.
- **Never submit a reading the user did not give you and the readings did not agree
  on.** A confident wrong captcha looks exactly like a wrong password from the outside.
- **Never call the engine twice for one login.** One attempt per login, then the human.
- **Keep it optional.** `CW_OCR=0` and the absent `ocr` extra must both keep the human
  path working exactly as it did. If a change breaks either, it is wrong.
- The captcha is the site's statement that a person is at the keyboard. This feature
  answers one round of it when the machine is measurably sure, and the person still
  answers the rest. Keep it that size; do not grow it.

The `viewer` page exists so the human step costs one round trip instead of several.
That is the design answer to a captcha, and the OCR is the answer to the *typing*, not
to the reading.

## The store

```
cw-data/
├── user.json                who this belongs to, and when it was last refreshed
├── assignments.json         every assignment across every course
├── index.html               the dashboard
└── courses/2824/
    ├── course.json          id, title, term, urls
    ├── assignments.json     just this course's rows
    ├── materials/           the user's files for this course
    ├── materials.json       the index of that folder
    └── notes.md             scratch space
```

Materials are a **folder convention**, not a claim about the site's markup: whatever
is in `materials/` is counted, and nothing else is asserted to exist. A file the user
saved by hand and a file a fetcher downloaded are the same thing downstream. Point the
user at `api.materials_text(course)["folder"]` and add files there.

The dashboard is one self-contained HTML file — the Persian font embedded as a data
URI, so it renders with no network and no install. It leads with what is actually
left, then a 30-day timeline, then counts, then one collapsible card per course.
Countdowns refresh themselves every 30 seconds from `data-due` attributes.

`api.build_dashboard()` writes it and returns the path without opening anything.
Showing it to the user is your call — preview the returned path.

## Why the API is shaped this way

Three things were removed because each one made this skill fail in practice, not as a
matter of taste:

- **No stdout.** A skill that shelled out and read Persian from a cp1252 console got
  mojibake, or wrote a temp file and read it back. Returning `str` skips that.
- **No prompts.** `input()` from a shell with no terminal raises `EOFError` and
  produces an error telling the user to set an environment variable. The login is two
  explicit calls now, so a non-interactive caller is the normal case.
- **No browser.** The old `ui` opened the page itself, which is a decision only the
  caller should make.

The CLI still exists, and it is still the right tool for a person at a terminal —
`cwtrack fetch`, `cwtrack ui`, `cwtrack gaps`, `cwtrack report -o out.md`. It calls
the same API, so it cannot disagree with you. Offer it when the user wants to run
something themselves or when the user needs to debug a parse failure.

## What the site actually is

Moodle, theme `mb2nl`, with the `local_logincaptcha` plugin.

**The official API does not work here.** Probed 2026-10-05:

| endpoint | result |
| --- | --- |
| `/login/index.php` | 200, works |
| `/login/token.php` | 200 but `{"errorcode":"enablewsdescription"}` |
| `/webservice/rest/server.php` | 403, empty body, blocked at nginx |
| `/webservice/rest/simpleserver.php` | 200, always an empty body |
| `/r.php/api/*` | 404, route absent on this install |

Browser login is the only way in. Do not spend time trying to enable a web-service
token: the endpoint that would consume it returns 403 before authentication is even
considered. Details in `references/moodle-api.md`.

## Rules

- **Only ever the user's own account.** Nothing here enumerates other students, and
  nothing that does should be added.
- **Unknown is not done.** `api.status()["unknown"]` is the list of things this tool
  refused to interpret. Report it. A parsing failure must never read as "submitted" —
  that is how a deadline gets missed twice.
- **Two substring traps are already handled and must stay handled.** `"not submitted"`
  contains `"submitted"`, and a `"Draft"` row with a stray number in the grade column
  is still not handed in. `references/parsing.md` explains the precedence; do not
  reorder `classify.py`.
- **Report the site's data, not your expectations.** If the site says submitted, it
  says submitted. If local files suggest otherwise, show both and let the user judge.
- **Read-only by construction.** No upload, no submit, no write to the site.
  Submitting is the user's click, in their browser, after they have read the work.
  Nothing in this skill or its neighbour should ever gain that ability.
- **Never claim a course has no assignments as a fact.** Say the pages showed none at
  the time of the check. Assignments get added mid-term.
- **A missing store is not an empty one.** If the API raises, say the data was not
  found and offer to fetch. Never report zeros you did not read from the store.

## Failure modes worth knowing

- `SSL: UNEXPECTED_EOF_WHILE_READING` — the site drops TLS under load, transiently.
  The client retries with backoff; a persistent failure means try again later.
- A course that fails to list is reported on stderr and skipped, so one bad course
  never yields a silently short report. **Check stderr before trusting a count.**
- Lots of `unknown` — the theme changed its table markup. Look at `.cw/dump/*.html`,
  fix the selectors in `src/cwtrack/parse.py`, run `cwtrack store` to re-parse
  without going near the network, and say what you changed.
- Persian showing as `???` — `PYTHONIOENCODING` was not set. Nothing is wrong with the
  data. This is the single most common way to draw a false conclusion here.
- The dashboard renders in Tahoma — the fonts are not being found. They ship inside the
  package at `src/cwtrack/fonts/`.