# logs/demo/ — synthetic demo inputs

These files are **hand-written demo inputs**, not captured evidence. They exist
so a live presentation can show all three violation types detecting, because the
real LogHub datasets in `logs/real/` contain **zero** lines that hit the
configured restricted resources and only a handful of successful logins.

`scripts/demo_feed.py` reads these read-only and replays them into `logs/live/`
with rewritten timestamps, exactly as it does for `logs/real/`.

| File | Real format | Triggers | Notes |
|------|-------------|----------|-------|
| `access_demo.log` | Apache Combined access log | `unauthorized_access` | `GET`/`POST` to `/admin`, `/wp-admin`, `/phpmyadmin`, `/config`, `/.env` → 403/401. Fed to `logs/live/access.log`, timestamp rewritten to "now". |
| `auth_demo.log` | Linux `sshd` syslog | `off_hours_login` | `Accepted password` for distinct users. Fed to `logs/live/auth.log`, timestamp rewritten to an **off-hours time today** (≈03:00) so it fires regardless of when the demo runs. |

These are safe to edit or regenerate. `logs/real/` is never modified by the demo.
`/` is deliberately **not** in `restricted_resources` — that was a one-time test
and stays reverted; these demo lines hit genuinely restricted paths instead.
