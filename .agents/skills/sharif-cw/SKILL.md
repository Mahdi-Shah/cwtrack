---
name: sharif-cw
description: 'Tracks the user''s own courses on the Sharif courseware site at cw.sharif.ir: fetches assignments, submission status, deadlines and grades into a local store, keeps each course''s material folder indexed, renders a single-page dashboard, reports what is still outstanding, and creates a working brief for one assignment. Use when the user asks which assignments are outstanding, what is due, what is late, what they already handed in, or asks to start work on an assignment — "تکالیفم را بررسی کن", "چیزی از قلم افتاده؟", "کدام تکلیف تحویل نشده", "مهلت‌ها کی است", "یه داشبورد از درس‌هام بساز", "برای این تکلیف بریف بساز". Logs in as the user through the browser login form; the site''s captcha is answered by a human, never by an automated solver. Read-only by construction, never fetches another student''s data, and never reports an unrecognised status as done.'
---

# Sharif courseware (cw.sharif.ir)

Answers one question properly: **what have I not handed in yet, and how late am I?**

It also keeps the rest in a place you can come back to — a store per course, your
material folders indexed, and one HTML page that shows the lot.

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

So browser login is the only way in. Do not spend time trying to enable a
web-service token: the endpoint that would consume it returns 403 before
authentication is even considered. Details in `references/moodle-api.md`.

## Where the code is

The implementation is the `cwtrack` package at the repo root, not inside this
skill. This skill is the operating manual for it.

```
src/cwtrack/
├── client.py      HTTP, cookies, retry
├── auth.py        login and the captcha
├── fetch.py       downloading pages
├── dates.py       Jalali/Gregorian, relative deadlines   <- pure, no I/O
├── classify.py    submission state -> verdict
├── parse.py       HTML -> assignment rows
├── match.py       finding unsent work on disk
├── tracker.py     the on-disk store
├── dashboard.py   the HTML
├── brief.py       the handoff to university-assignment
└── cli.py         argparse

.agents/skills/sharif-cw/
├── SKILL.md
├── references/parsing.md       selectors, status words, precedence, Jalali
└── references/moodle-api.md    what the official API would have been
```

## Running it

Installed (`pip install -e .` from the repo root):

```
cwtrack <command>
```

Not installed:

```
python -m cwtrack <command>      # needs the repo's src on PYTHONPATH
```

Both accept `--data <folder>` to point at a specific store. Without it the nearest
`cw-data` is found by walking up from the current directory, then from the package
location. A missing store raises rather than reporting zeros — "you have no
assignments" and "I could not find your data" are opposite claims.

## Commands

```
cwtrack fetch                  log in, download every course's assignment page, store it
cwtrack ui                     build cw-data/index.html and open it
cwtrack gaps                   what is left, worst first
cwtrack open                   the short list of outstanding work
cwtrack report -o out.md       the full Persian markdown report
cwtrack brief                  create a working folder for what is outstanding
cwtrack brief --cmid 42694     ...for one named assignment
cwtrack material --course 2824 print (and create) that course's material folder
cwtrack store                  re-parse an existing dump into the store, no network
cwtrack raw                    list the saved HTML
cwtrack open --local <dir>     also flag work that exists on disk but was never uploaded
```

`fetch` stores as well as downloads, on purpose: a fetch that never lands in the
store is a fetch you cannot query.

`store`, `ui`, `gaps`, `open`, `report`, `brief` and `material` read the store only.
They work with no network and no captcha.

`brief` writes to `work/` beside the store unless `--work` says otherwise. It will
not overwrite an existing folder without `--force`, because the brief's sections 2
to 7 are the user's own writing.

## The store

```
cw-data/
├── user.json                who this belongs to, and when it was last refreshed
├── assignments.json         every assignment across every course
├── index.html               the dashboard
└── courses/
    └── 2824/
        ├── course.json      id, title, term, urls
        ├── assignments.json just this course's rows
        ├── materials/       your files for this course
        ├── materials.json   the index of that folder
        └── notes.md         scratch space
```

Materials are a **folder convention**, not a claim about the site's markup: whatever
is in `materials/` is counted, and nothing else is asserted to exist. A file the user
saved by hand and a file a future fetcher downloads are the same thing to everything
downstream. `cwtrack material --course <id>` prints the path and lists what is in it.

## The dashboard

One self-contained HTML file — the Persian UI font embedded as a data URI, so it
renders with no network and no install. Leads with what is actually left, then a
30-day timeline, then counts, then one collapsible card per course with a progress
bar, a countdown per assignment, a status badge, the site's own deadline text, the
mark, and a link that opens the assignment on cw.

The page refreshes its countdowns every 30 seconds from `data-due` attributes, so a
tab left open overnight does not quietly become wrong.

## `brief` — the handoff to the other skill

`cwtrack` knows an assignment exists and when it is due. `university-assignment`
knows how to produce the document. `brief` writes the file that connects them:

```
work/<course>/<assignment>/
├── brief.md      everything the site knows, and what it does not
├── HANDOFF.md    what to do next, in order
├── draft.md      where the answer goes
└── source/       course material
```

The brief fills in title, course, term, deadline, countdown, status and link. It is
explicit about the one thing the site does not give us — the assignment text — so
nobody solves the wrong question confidently.

After `brief`, hand the folder to `university-assignment`. It reads `brief.md` and
the material in `source/`.

## The captcha, and why there is no solver

The login form carries an image captcha. `cwtrack` saves the image and asks a human
to read it. It will not solve it.

Three reasons, in order of weight:

1. The captcha is the site's explicit statement that a human is at the keyboard. A
   solver is a bot-evasion tool, not a study aid, and shipping one inside a package
   that sits next to someone's coursework files is a bad trade.
2. It would be wasted effort. There is exactly one network entry point and the
   captcha is on all of it.
3. It would be unreliable. Distorted-character captchas defeat OCR often enough that
   you would be re-running it constantly.

**Practical tip that matters more than it sounds:** the captcha image is about
190×40 px and is genuinely hard to read at that size. If a read is rejected, just
run `fetch` again and try once more with the image zoomed.

## Credentials

Never write the password into a file, a script, or a command line. Environment or a
no-echo prompt:

```powershell
$env:CW_USER = "<your student number>"
$env:CW_PASS = "<your password>"   # optional; prompted with no echo if absent
```

Or let it prompt:

```powershell
cwtrack fetch
```

**Rotate the password.** If it has been pasted into a chat, an issue or a screenshot,
it is in history that stays. cw.sharif.ir's own login page currently asks every user
to reset through *forgot password* anyway, so this is a live issue on that site
rather than a precaution — and if the credentials stop working, try that first
instead of suspecting the script.

## Workflow

### 1. Fetch

```powershell
cwtrack fetch
```

Saves `/my/courses.php`, the dashboard, and the assignment page for every course
into `.cw/dump/`, then writes the store.

The raw save is not decoration. The parsers are written against Moodle's structure
but the site only started serving the assignment table for some courses, so the dump
is what a parsing failure is diagnosed against.

### 2. Look

```powershell
cwtrack ui          # the dashboard, opened in a browser
cwtrack gaps        # the same thing as text, for a quick check
```

When reporting to the user, lead with what is overdue and what is due soon. The full
table is supporting detail, not the point.

### 3. Hand over

```powershell
cwtrack brief                    # lists what is outstanding, then picks with --cmid
cwtrack brief --cmid 42694
```

Then run `university-assignment` on the folder it created.

## Rules

- **Only ever the user's own account.** Nothing here enumerates other students, and
  nothing that does should be added.
- **Unknown is not done.** An unrecognised status lands in `unknown` and is called
  out in both the report and the dashboard. A parsing failure must never read as
  "submitted" — that is how a deadline gets missed twice.
- **Two substring traps are already handled and must stay handled.** `"not
  submitted"` contains `"submitted"`, and a `"Draft"` row with a stray number in the
  grade column is still not handed in. `references/parsing.md` explains why the
  precedence is ordered the way it is, and `tests/test_parse.py` guards it.
- **Report the site's data, not your expectations.** If the site says submitted, it
  says submitted. If local files suggest otherwise, show both and let the user judge.
- **Read-only by construction.** No upload, no submit, no write to the site.
  Submitting is the user's click, in their browser, after they have read the work.
- **Never claim a course has no assignments as a fact.** Say the pages showed none at
  the time of the check. Assignments get added mid-term.

## Failure modes worth knowing

- `ورود ناموفق بود` with no specific message — check whether the password was reset via
  *forgot password* before assuming the script is wrong.
- `SSL: UNEXPECTED_EOF_WHILE_READING` — the site drops TLS under load, transiently.
  The client retries with backoff; a persistent failure means try again later.
- A course that fails to list is reported on stderr and skipped, so one bad course
  never yields a silently short report. **Check stderr before trusting a count.**
- Lots of `unknown` — the theme changed its table markup. Look at
  `.cw/dump/course_*.html`, fix the selectors in `src/cwtrack/parse.py`, and say what
  you changed.
- Persian mojibake in the terminal — that is the Windows console codepage (cp1252),
  not the script. Every text-producing command takes `-o`, so write to a file and
  read that instead. `Get-Content` also guesses the codepage on the way back in, so
  ask for UTF-8 explicitly:

  ```powershell
  cwtrack gaps -o gaps.txt
  Get-Content gaps.txt -Encoding UTF8
  ```
- The dashboard renders in Tahoma — the fonts are not being found. They ship inside
  the package at `src/cwtrack/fonts/`; a wheel built without that path degrades
  silently, which is what the CI font check guards against.