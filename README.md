# cwtrack

Track your own assignments, deadlines and course material on **cw.sharif.ir** — the Sharif University courseware — and see at a glance what you still owe.

Two OpenCode skills and a small Python package. Zero required dependencies, no server, no telemetry.

```powershell
cwtrack fetch     # log in, download, store
cwtrack ui        # open the dashboard
cwtrack brief     # start a working folder for what's due
```

[فارسی](README.fa.md) · [MIT](LICENSE)

---

## What it does

| Command | |
|---|---|
| `fetch` | Logs in, downloads every course's assignment page, writes the store |
| `ui` | Builds a self-contained HTML dashboard and opens it |
| `gaps` | What's outstanding, worst first — the short version |
| `open` | Just the outstanding list |
| `report -o out.md` | Full Persian markdown report |
| *any of these + `-o file`* | *write to a file instead of stdout* |
| `brief` | Creates a working folder with a pre-filled brief for one assignment |
| `material --course N` | Prints and lists that course's material folder |
| `store` / `raw` | Re-parse an existing dump / list the saved HTML |

Everything except `fetch` reads local files only. No network, no captcha.

`-o` works on every text-producing command, which is worth knowing because Persian
output is mangled by a stock Windows console (cp1252):

```powershell
cwtrack gaps -o gaps.txt
Get-Content gaps.txt -Encoding UTF8
```

## Install

```powershell
git clone https://github.com/OWNER/cwtrack
cd cwtrack
pip install -e .
```

Or run it without installing:

```powershell
python -m cwtrack --help        # needs src on PYTHONPATH, or use pip install -e .
```

Python 3.9+. The only optional extra is `jdatetime`, which improves Jalali conversion
outside the bundled table:

```powershell
pip install -e ".[calendar]"
```

## Why there is a dashboard and not just a table

A table of dates does not tell you that three things are all due tomorrow. The
dashboard leads with **"الان چه کاری مانده"** — what is actually left — then a
30-day timeline, then counts, then one collapsible card per course.

Deadlines that fall on the same day share one tick with their labels stacked, so a
busy day is one marker with several names rather than several markers fighting for
the same pixel.

It is one HTML file with the fonts inlined as data URIs. No server, no build step,
nothing to install to view it. Countdowns refresh themselves every 30 seconds, so
a tab left open overnight does not quietly become wrong.

## `brief` — the seam to the other skill

`cwtrack` knows an assignment exists and when it is due. `university-assignment`
knows how to produce the document. `brief` writes the handoff:

```
work/<course>/<assignment>/
├── brief.md      everything the site knows, and what it does not
├── HANDOFF.md    what to do next, in order
├── draft.md      where the answer goes
└── source/       course material
```

`brief.md` is explicit about the one thing the site does not give us — the
assignment text — so nobody solves the wrong question confidently. It refuses to
overwrite an existing folder unless you pass `--force`, because sections 2 to 7 are
yours.

## The captcha

cw.sharif.ir puts an image captcha on the login form. `fetch` saves the image and
asks you to read it.

**It is not solved automatically, and will not be.** The captcha is the site's
explicit statement that a human is at the keyboard; an automated solver is a
bot-evasion tool rather than a study aid, and shipping one inside a package that
lives next to your coursework files is a bad trade. It would also be unreliable —
distorted-character captchas defeat OCR often enough that you would be re-running
it constantly.

One practical tip: the image is about 190×40 px and is genuinely hard to read at
that size. If it is rejected, just try again.

## Scope, honestly

**Verified against cw.sharif.ir only.** Not other Moodle sites, not other
universities.

The theme (`mb2nl`), the Jalali deadlines, the captcha plugin and the four-column
assignment table are all specific to that deployment. The Moodle *structure* is
generic, but I have no way to test a generic adapter, and shipping one I cannot run
would be a claim rather than a feature. So the tool says what it is.

Known limitations, all tested and documented rather than quietly worked around:

- **English filenames are matched loosely.** `HW4_Oscillator.pdf` does not match
  `Homework 4 — Oscillator`; they share one token and the matcher requires two.
  Persian filenames fold correctly (ک/ك, ی/ي, Persian and Arabic digits, ZWNJ).
- **A missing store fails loudly.** It never reports zero, because "you have no
  assignments" and "I could not find your data" are opposite claims.
- **An unrecognised status is never `submitted`.** It lands in `unknown` and is
  called out in the report. A parsing failure must not read as a finished
  assignment.
- **"Nothing found" is not "nothing exists."** A course showing no assignments means
  that at the last check it had none. Assignments get added mid-term.

## The Jalali calendar

Deadlines on this site are Persian and usually carry no year: `Tomorrow, 14 مهر, 7:30 صبح`.

Conversion prefers `jdatetime` when installed. Otherwise an embedded Nowruz table
covers Jalali 1380–1442 (2001–2061), which is any current or near-future term.
Outside that range it returns nothing rather than guessing.

That table was validated against four invariants, because the short "33-year
formula" conversions that circulate online are wrong often enough to matter — two
attempts in this project placed Nowruz on 22 March and produced 364- and
367-day years:

- Nowruz always falls on 20 or 21 March across the range
- Year length is always 365 or 366
- Exactly 8 leap years per 33-year cycle
- Every day of a year maps to consecutive Gregorian days, and both code paths
  agree on every day of a three-year span

## Safety

**Read-only against the site.** There is no upload, no submit, and no write of any
kind. Submitting your work is your click, in your browser, after you have read it.

**Only your own account.** Nothing here enumerates other students, and nothing that
does should be added.

**Your data stays on your machine.** `cw-data/`, `.cw/`, `work/` and `reports/` are
gitignored, and so are `.env`, token files and session files. Raw page captures
contain a live `sesskey` in the logout URL — never commit one.

**Credentials never touch a file.** They come from `CW_USER` / `CW_PASS` in the
environment, or a prompt with echo off. Not from argv, which would put them in shell
history.

## Development

```powershell
pip install -e ".[dev]"
pytest              # 277 tests, 1 skipped, no network, no account needed
ruff check src tests
```

Install from a clean clone before you trust a green run. Most of the bugs found
while building this were invisible to the working tree and only appeared once the
package was installed somewhere else — a missing dev dependency, an asset the wheel
dropped, an import-time guard that only fires on a real console.

Tests run entirely on sanitised fixtures in `tests/fixtures/` — the shape of the real
page, with every identifier replaced. No test reads a real capture.

The two places bugs actually lived are the two best-tested modules:

- `dates.py` — properties over ranges, not examples. A single anchor would have
  passed both broken Jalali implementations.
- `classify.py` — the precedence is tested as a whole because two substring facts
  drive it: `"not submitted"` contains `"submitted"`, and a draft is not a
  submission. An earlier version got this backwards and reported four undone
  assignments as handed in.

## Layout

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
├── brief.py       the handoff
└── cli.py         argparse

.agents/skills/
├── sharif-cw/              this tool, as an OpenCode skill
└── university-assignment/  turns an assignment into a submittable PDF
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md).

## License

MIT. Bundled fonts are SIL OFL 1.1 — see [LICENSE](LICENSE).
