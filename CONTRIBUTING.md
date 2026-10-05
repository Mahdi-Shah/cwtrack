# Contributing

Contributions are welcome. This is written for Sharif students, and a bug report
with real markup attached is the most useful thing you can send.

[فارسی](CONTRIBUTING.fa.md)

---

## Setup

```powershell
git clone https://github.com/Mahdi-Shah/cwtrack
cd cwtrack
pip install -e ".[dev]"
```

Without installing:

```powershell
python -m pytest tests
```

**The tests need no network and no account.** They run entirely on sanitised fixtures
in `tests/fixtures/`. If a test ever needs to reach the network, it is written wrong.

```powershell
pytest                        # everything
pytest tests/test_dates.py -v # one file
ruff check src tests          # must be clean
```

Run the suite both ways before pushing — once as-is, once with `jdatetime`
uninstalled. The embedded Nowruz table only runs in the second case, so a broken
table otherwise ships unnoticed:

```powershell
pytest
pip uninstall jdatetime && pytest
pip install jdatetime
```

## What helps most

**A bug report with real markup.** If the parser missed the page, you can see what
it missed. Please **strip the identifying parts** — name, student number, email,
course ids — before attaching. What helps:

```powershell
cwtrack fetch          # what exactly happened?
cwtrack raw            # how many pages were saved?
cwtrack gaps           # how many assignments came out? does that seem right?
```

If a status was read wrong, one row of the table is enough. Open
`.cw/dump/cNNN_assign.html`, find the row, and show it.

**Extending coverage to courses that currently do not work.** If the theme changed
its table markup, the selectors are in `src/cwtrack/parse.py` and the expectations
are in `tests/fixtures/`.

## Rules

**1. Write the test before the fix.**

This project has had bugs that only a test could find. The worst one reported every
unsubmitted assignment as submitted, because `"not submitted"` contains the string
`"submitted"`. If you add a regression test for a bug you fix, several other people
will avoid re-introducing it.

**2. Test the Jalali calendar with properties, not examples.**

One anchor for year 1404 passes both broken conversions in this project's history.
Write a test over a range instead — see `tests/test_dates.py` for the pattern.

**3. Do not commit real data.**

`cw-data/`, `.cw/`, `work/` and `reports/` are gitignored. A raw page capture
contains a live `sesskey` in the logout URL.

If you must attach a file to reproduce a problem, strip it first. A good fixture
keeps the real shape and carries no identifiers — see
`tests/fixtures/course_90000_assign.html`.

**4. Do not call something working if you have not tested it.**

If you only tested against cw.sharif.ir, do not write "supports other Moodle sites".
Honesty about scope is good for the user and good for the project.

**5. Do not touch another student's data.**

This tool reads your account and nothing else. Do not add a code path that enumerates
other students. If you find one, report it.

**6. The captcha does not get solved automatically.**

Please do not propose OCR for it. The reasoning is in the README; in short, the
captcha is the site's statement that a person is at the keyboard.

## Style

- Max line length 96 (`ruff`)
- User-facing messages and comments in Persian; code and identifiers in English
- Readability over density: long Persian strings read better with `.format` than
  f-strings
- Functions pure where possible — `dates.py` is the model

## Two things that will bite you

**Every text-producing command must honour `-o`.** Persian on a stock Windows console
is cp1252 and comes out as mojibake, so writing to a file is the documented
workaround. Route new output through `cli.emit()` rather than `print()`.

**A named font that is not embedded fails silently.** The dashboard degrades to
Tahoma with no error. The fonts ship inside the package at `src/cwtrack/fonts/`, and
there is a CI check that the wheel contains them. If you add an asset, declare it in
`[tool.setuptools.package-data]`.

## Commitment

Treat each other with respect in discussions. This project is about coursework and
universities, not about people.