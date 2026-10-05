# Security policy

## Scope

`cwtrack` is a read-only tool. It reads one Moodle account — your own — and writes
files to your disk. It has no server component, no telemetry, and no update
mechanism.

### What it deliberately cannot do

- **Submit, upload, or modify anything on the site.** There is no code path that
  writes to cw.sharif.ir.
- **Enumerate other students.** `core_enrol_get_users_courses` is called with the
  id read from your own token, and nothing walks the user list.
- **Solve the login captcha.** It is saved and read by a human. This is on purpose:
  the captcha is the site's statement that a person is at the keyboard.

If a pull request adds any of the above, it will not be merged.

## Reporting a vulnerability

Open a private security advisory on the repository, or email the maintainer if
advisories are unavailable.

Please include: what you did, what you expected, what happened, and a minimal
reproduction. Do **not** include a real capture of your coursework page — those
contain a live `sesskey` in the logout URL.

## Handling credentials

Credentials come from `CW_USER` / `CW_PASS` in the environment, or a no-echo
prompt. They are never read from argv, because argv is visible in shell history and
in the process list.

If you pasted a password into a chat, an issue, or a screenshot: **change it.**
Those places keep history. The cw.sharif.ir login page also currently asks every
user to reset their password through *forgot password*, so this is worth doing
regardless.

## What must never be committed

`.gitignore` covers all of it, but verify before pushing:

| Path | Why |
|---|---|
| `cw-data/` | name, student number, email, course ids, marks |
| `.cw/` | raw authenticated HTML containing a live `sesskey` |
| `work/`, `reports/` | assignment text and your answers |
| `.env`, `secrets.json`, `token.txt` | credentials and web-service tokens |
| `session.json` | session marker |

A Moodle `sesskey` is a bearer token. Anyone holding it can act as you for that
session. Treat one as a leaked password and reset it.
