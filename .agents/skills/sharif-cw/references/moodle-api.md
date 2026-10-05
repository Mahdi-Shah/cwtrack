# The Moodle API — and why this skill does not use it

Kept for the day cw.sharif.ir enables web services, and as a record of what was checked. Nothing in `cwtrack` calls any of it today.

## Probe results, 2026-10-05

Run with a plain stdlib client and a browser User-Agent. No credentials were used, so nothing here reflects an account's permissions.

| endpoint | result |
| --- | --- |
| `/login/index.php` | 200, 61 KB, login form present |
| `/login/token.php?wsfunction=...` | 200, JSON error `enablewsdescription` |
| `/webservice/rest/server.php` | **403, zero-length body** |
| `/webservice/rest/simpleserver.php` | 200, always a zero-length body |
| `/webservice/xmlrpc/server.php` | 404 |
| `/r.php/api/*` | 404 |
| `/webservice/rest/nonexistent.php` | 404 with a normal HTML error page |

Two things worth noting about the 403. The body is empty and `Content-Type: text/html` served by `nginx`, not a Moodle JSON error — Moodle answers a bad token with HTTP 403 *and* a JSON body. And a nonsense path in the same directory returns a proper 404, so the block is specific to `server.php` rather than to the directory.

`login/token.php` answering with a well-formed Moodle error is the useful signal: the endpoint is reachable, it just refuses because web services are not enabled for the account. Enabling them changes nothing here, because the endpoint that would consume the token is refused earlier, at the proxy.

**Conclusion: browser login is the only working path.** `cwtrack` does that.

## What the API would have given us

Worth recording, because it is strictly better than scraping and worth revisiting if the site changes.

```
GET /webservice/rest/server.php
    ?wstoken=<token>
    &wsfunction=<function>
    &moodlewsrestformat=json
```

The three calls that would do the whole job:

**`core_webservice_get_site_info`** — no parameters. Returns `userid`, `username`, `fullname`, `moodleversion`. The `userid` comes from here rather than from argv, which is what structurally prevents pointing the tool at another student.

**`core_enrol_get_users_courses`** — `userid`. Every enrolled course.

**`core_assign_get_assignments`** — `courseids[]`, one course per call. The useful part is `submissionstatus`:

```
submissionstate   submission_state | no_submission | draft | submitted | graded
timesubmitted     epoch, 0 if never
graded            bool
grade             the mark, or null
needsgrading      a real submission is queued for marking
draft             bool
extensionduedate  a teacher's extension, outranks `due`
```

`submissionstatus` is where the current scraping path has to work harder. The `mb2nl` table gives you four flat cells and a status string in one of six languages' worth of phrasing, whereas this gives you an explicit state enum — which is exactly what removes the `"not submitted" contains "submitted"` class of bug. See `parsing.md` for the precedence that substitution forced.

**`core_grades_get_grades_by_user`** — `userid`, `courseid=0` for all courses.

Cost would have been `2 + N` requests for `N` courses, against `1 + N` HTML pages today.

## If web services ever get enabled

1. Profile → Preferences → Advanced → **Web services: Enable**, then **Manage tokens** → add one for `Moodle mobile app`. Treat the token as a password; revoke from the same page.
2. `cwtrack` would gain a token path. It is not written today — the session-mode
   rewrite dropped it rather than ship dead code — so expect to re-add
   `rest()` plus a `collect()` built on `core_assign_get_assignments`. The
   classification logic transfers unchanged: it keys off `submissionstate`
   rather than off scraped prose, which is exactly what removes the
   `"not submitted" contains "submitted"` class of bug described in `parsing.md`.
   Keep the `needsgrading` and `extensionduedate` handling from `classify()`.
3. Check `webservice/rest/server.php` returns JSON rather than a proxy 403 *first*. A token is useless while nginx refuses the path.

Do not assume step 1 succeeded just because the preferences saved. Probe the endpoint.
