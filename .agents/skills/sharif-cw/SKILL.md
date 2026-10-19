---
name: sharif-cw
description: 'Tracks the user''s CW coursework and Quera assignments, checks connected course materials across both platforms, and manages durable solution revisions and verification evidence. Use when the user asks what is due, what is late, to start, continue, revise or solve coursework, or to see progress — "تکالیفم را بررسی کن", "تکالیف کوئرا", "چیزی از قلم افتاده؟", "کدام تکلیف تحویل نشده", "مهلت‌ها کی است", "تکلیفمو حل کن", "ادامهٔ تکلیفم", "منبع این درس را اضافه کن". The user speaks; you call the API. Credentials are supplied by the user and saved in Windows-protected storage. CW captcha OCR may need the user to read an image; the user supplies OTPs. Quera listing/detail and CW course-resource retrieval have offline fixture coverage; live account acceptance and interactive CAPTCHA continuation remain incomplete.'
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

For the shared catalog, call `api.study_view()` and `api.study_refresh()`; these read
the multi-platform projection and refresh configured connections independently. The
older `api.status()` and `api.outstanding()` calls remain the CW-only compatibility
view. Never infer an empty cross-platform inbox from an unavailable or incomplete
target.

### 1. Refresh, if the data is stale

`api.status()["refreshed"]` says how old the submission statuses are. Countdowns are
computed live and are always current; statuses are not. Refresh when it is older than
today, or when the user asks for the current picture.

### 2. Answer from `status()`

**Lead with what is overdue, then what is due soon. The full list is supporting
detail, not the point.** Say what is left, in how long, and what it is — not "you have
2 open items in 1 course".

### 3. Start, resume, and complete selected work

Start only after the user selects an assignment or explicitly asks for a group such as
everything due this week. For an ambiguous selection, show the open assignments from
`api.outstanding()` for the legacy CW store or `api.study_view()` for the shared
catalog, then ask which item or group they mean. Keep the user's stated priority when
ordering a selected group.

When the assignment is listed in `api.study_view()["platform_assignments"]`, use its
exact `ref` with `api.study_prepare({"task_ref": ref})`. This is the shared CW/Quera
path: it retrieves the selected prompt, creates or resumes the stable work record, and
returns resources bound to both that exact task and its explicitly linked course
offering. It also returns `course_sources`, one result per connected platform source.
Inspect these results and their coverage before solving; an overall `ok` does not mean
an unlinked or unchecked source was searched. A linked CW offering is queried for its
visible course-page and resources-list files; downloaded files are registered to the
offering and captured as immutable resources.

If a source reports `link_required`, compare the target class and candidates using an
exact course code when both expose one, and confirm the same term. If the code is absent,
link only when the course identity and term are otherwise clear and unique. Use
`api.course_link([target_class_ref, candidate_ref], offering, expected_revision=...)`
to persist that confirmed relationship, then run `study_prepare` again. If several
candidates remain or the term is unclear, ask the student once and keep preparation
`partial` until they identify the class. Never link classes from a similar name alone.

Treat `not_configured`, `needs_refresh`, `link_required`, `no_candidate`, and
`local_library_only` as distinct outcomes. A `no_candidate` result only says the last
complete class inventory had no match; it does not prove the course has no resources.
If CW reports `challenge_required`, continue that exact operation with
`api.study_continue()` and then retry preparation. Report incomplete or unavailable
coverage per source; do not collapse it into “no materials found.” Read the returned
resource snapshots before solving. Use the older CW `cmid` path below for legacy-only
course stores or when the shared connection inventory is not available.

For a site assignment, call `api.collect_assignment({"site": {"cmid": id}})`. The
assignment must already be in the local store. Handle `needs_credentials`,
`captcha_required`, `captcha_rejected`, `not_found`, `needs_input`, and `failed` as
separate states; never treat an incomplete fetch as an empty assignment. For a file or
text the user supplied, pass a `manual` source with its course, title, prompt and
attachment paths. `collect_assignment` extracts text from `.txt`, `.md` and `.csv`;
read other formats with the matching document skill and retain the original file.

Create or resume the durable record with:

```python
started = api.work_start({"received": intake["input"]})
work_id = started["work_id"]
current = api.work_get(work_id)
```

If the start result is `exists`, resume that item. When `input_changed` is true, call
`api.work_sync(work_id, intake["input"], expected_revision=current["revision"])` and
re-read it. A changed prompt or attachment requires reassessing affected work; a
deadline-only change does not invalidate the answer. For a manually supplied source,
`api.work_start({"manual": {...}})` is also supported. Save progress with
`api.work_save(..., expected_revision=current_revision)` after each material step;
always use the revision just returned to avoid overwriting another checkpoint.

For an explicitly selected group, collect each selected item's input first, then call
`api.work_group_start([{"received": input_a}, {"received": input_b}, ...])`. It orders
members by the user's priority and deadline and returns a `group_id`. Save that id in
the conversation summary; `api.work_group_get(group_id)` resumes the same fixed list
after new assignments appear. A member with `input_changed=true` needs `work_sync`
before continuing; when resuming later, refresh each selected site item and sync any
changed prompt or attachment. A partial result keeps each successful member and
reports the failures separately.

Use the **`university-assignment` skill** to read the assignment and course materials,
solve the requested work, choose the required formats, and run checks suited to the
assignment type. Save the response sections, requirements, sources, open questions,
and check evidence through `work_save`. Checks must name their `requirement_id`,
method, result, evidence, and the current `input_fingerprint` and `answer_fingerprint`
from the saved record. Do not invent missing experimental data or claim a check that
was not run.

Call `api.work_finish(work_id, delivery, expected_revision=...)` with the actual output
file paths, their roles, and a delivery note. It copies the files into the saved work
history. Report `ready_for_student_review` only when the API returns `status="ok"`;
when it returns `needs_completion`, address the listed gaps or explain them. The
student reviews and uploads the files themselves. `api.work_list()` resumes existing
items without starting or solving anything; `api.make_brief()` remains available for
the older brief-only workflow.

## Quera and supplementary course resources

Quera's current adapter can authenticate, discover class links, read an assignment list,
retrieve the selected prompt and downloadable attachments, and inspect visible course
material links. Submission state and grades remain unknown. These paths have offline
fixture coverage; live account acceptance and interactive CAPTCHA continuation are
still unverified. If refresh or detail retrieval is incomplete, report that state
rather than saying there is no homework. For assignment work, use an exact opaque
`assignment_ref` and the received prompt with the same durable workflow:

```python
prepared = api.study_prepare({"received": {
    "source": "quera",
    "assignment_ref": task_ref,
    "course": course_title,
    "term": term_if_known,
    "title": title,
    "prompt": prompt,
    "url": assignment_url,
    "attachments": [{"path": file_path, "role": "prompt"}],
}})
```

Do not invent IDs, deadlines, completeness or a successful submission state. If the
user has no stable task reference, use the manual-input workflow and mark its source
accordingly. Quera's login needs the user's supplied credentials and may ask for an
OTP. The current reCAPTCHA response cannot be transferred from a browser challenge to
the local HTTP session, so report it as an unresolved interactive challenge.

When the student explicitly says two exact tasks are related, record that relationship
with `api.assignment_relate(task_refs, reason, expected_revision=view["catalog_revision"])`.
This annotation never merges their work IDs, submission states or checks. A prior
answer may serve as a draft only after mapping the new task's requirements; rerun the
new task's checks and preserve its own delivery history.

For a CW account connection, use the interactive terminal command `cwtrack connect`.
It asks for the username and reads the password with hidden terminal input, then stores
the account through `api.access_configure("cw", credentials)` in the Windows DPAPI
vault. Open a visible Codex terminal and start the command for the user; never ask the
user to put a CW password in chat, a command argument, or an environment variable for
this shared connection. Continue the coursework refresh after the command succeeds.

When the user asks to connect another account and supplies its values, pass the
supplied values directly to the API and keep them out of summaries, logs, shell
commands and returned prose:

```python
connection = api.access_configure("quera", credentials)
rotated = api.access_update(
    connection_id, replacement_credentials,
    expected_generation=current_credential_generation,
)
api.access_forget(connection_id)
```

The default protected vault uses Windows DPAPI. If it returns
`secure_store_unavailable`, report that state; never save credentials in plain JSON or
substitute a plaintext fallback. Reconfiguring credentials invalidates old sessions and
pending challenges. An OTP response resumes that saved attempt with
`api.study_continue(continuation_id, {"kind": "otp", "value": code})`.

Attach a supplementary resource once to the chosen course offering or exact task:

```python
attached = api.resource_attach(
    {"title": title, "location": {"kind": "file", "path": path}},
    to={"offering_id": offering_id},
    extent={"pages": "14-22"},
)
snapshot = api.resource_capture(
    attached["resource_id"], extent={"pages": "14-22"}
)
materials = api.resource_view(target={"offering_id": offering_id})
```

`folder` accepts an explicit `extent={"files": [...]}` and captures only those files;
`web` and `remote_file` capture the retrieved public response; `video` remains a
reference until an actual transcript or selected content is supplied. Capture is not
proof of use. Open and read the actual snapshot before citing it, record the precise
parts and extent through `work_save(resource_uses=...)`, and let the API validate the
snapshot hash and binding. Course official material and assignment constraints take
precedence over supplements. Use a resource only within the captured extent.

## CW CAPTCHA: Python first, then the user

`api.study_refresh()` runs Python OCR for up to **10 fresh CAPTCHA rounds** per login.
It stops immediately on success. Each round runs the existing ensemble on one image;
its multiple Tesseract readings count as one round. A low-agreement reading is not
submitted: Python downloads a fresh image for the next round. A rejected submission
continues with the fresh image already returned by the site. The same policy applies
to legacy `api.refresh()` and terminal `auth.do_login()`.

Let Python perform these rounds. Model vision is not the user's requested automatic
reader. When a shared refresh returns a `readable_code` action:

1. Inspect `challenge.display.ocr`: `attempts`, `limit`, `exhausted`, and `reason`.
   After ten unsuccessful rounds, `exhausted` is true. `read` describes the previous
   attempted image; it is not a proposed answer to the fresh image.
2. Show `challenge.display.viewer` to the user at its enlarged size and ask for the
   characters. If the viewer cannot be displayed, show the image enlarged.
3. Resume the exact operation with
   `api.study_continue(continuation_id, {"kind": "readable_code", "value": answer})`.
   Handle any new challenge returned by that continuation. Restarting refresh would
   start a new automatic budget instead of continuing the user's response.
4. Report coursework only after checking the continuation's refresh result. Successful
   login does not prove that classes or assignments were retrieved.

For legacy `api.refresh()`, the returned `captcha_required` or `captcha_rejected`
state carries `image`, `viewer`, and `ocr` directly. Resume with `captcha=answer`;
an explicit answer bypasses OCR rather than restarting its budget. The terminal
allows at most three user answers after the automatic rounds.
Existing `CW_USER` / `CW_PASS` configuration remains a legacy input. For the shared
account, use the protected interactive `cwtrack connect` flow described above.

`CW_OCR=0` deliberately disables automatic reading. Missing Tesseract/Pillow, corrupt
images, or engine errors are reported as technical failures, not ten completed OCR
rounds. Check and report that cause instead of repeatedly invoking a broken engine.
Credentials failures and network errors also stop the automatic loop. Keep the OCR
extra optional and credentials in their protected connection flow.

The ensemble still requires 70% agreement before automatic submission. Its historical
20-sample measurement concerns individual images; it does not establish the success
rate of ten-round live logins. The student's clarified policy is recorded in
[the CW connection design](../../../docs/cw-account-connection.md).

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
