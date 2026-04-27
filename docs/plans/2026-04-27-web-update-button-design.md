# Web Update Button — Design

## Goal

Let parents check for and install updates from the web Settings page,
instead of waiting for the boot-time auto-update. The Settings page
auto-checks on load, shows whether an update is available, and offers
a one-click update button.

## User Flow

1. User opens **Settings**.
2. New "Software Updates" card auto-fires `GET /api/update/check`.
3. Card shows one of:
   - Spinner while checking.
   - "Up to date" + current commit SHA.
   - "Update available" badge + "Update Now" button.
   - Error message + retry button if the check failed (offline, etc.).
4. User taps **Update Now** → `POST /api/update/start`.
5. UI flips to "Updating… the box will restart shortly" and disables
   the button. Backend spawns a transient systemd unit running
   `manual-update.sh`, then returns immediately.
6. The update script pulls main, reinstalls deps if needed, and
   restarts `flockify.service`. Web UI may briefly disconnect; user
   reloads to see new version.

## Components

### `scripts/manual-update.sh` (new)

- Reuses `scripts/auto-update.sh` for the actual git pull + deps logic.
- After update succeeds, runs `systemctl restart flockify.service`.
- Logs to journald (tagged `flockify-manual-update`).
- Exits 0 even if no update was available (idempotent).

### Sudoers drop-in `/etc/sudoers.d/flockify-update` (installed by install.sh)

```
pi ALL=(root) NOPASSWD: /home/pi/flockify/scripts/manual-update.sh
```

Narrow scope — only this one script.

### Flask endpoints (in `web/app.py`)

- **`GET /api/update/check`** — returns:
  ```json
  {
    "current_sha": "7d41198",
    "current_subject": "feat(web): redesign UI…",
    "latest_sha": "abc1234",
    "latest_subject": "feat: add update button",
    "update_available": true,
    "behind_count": 2,
    "checked_at": "2026-04-27T12:34:56Z",
    "error": null
  }
  ```
  Implementation: `git rev-parse HEAD` for local, `git ls-remote
  origin main` for remote. Use `git log` to fetch subjects (after a
  `git fetch` with a 10s timeout). Cached for ~30s server-side to
  avoid hammering GitHub on tab refreshes.

- **`POST /api/update/start`** — spawns the update via:
  ```
  sudo systemd-run --unit=flockify-manual-update \
       --collect /home/pi/flockify/scripts/manual-update.sh
  ```
  Returns `{"started": true}` within ~100ms.

### Settings UI

New card at the top of `settings.html` (above WiFi):
- Title: "Software Updates"
- Status row: badge ("Up to date" / "Update available" / "Checking…" /
  "Error") + current short SHA + commit subject (truncated).
- "Update Now" button — only visible when update available.
- "Check Again" link below.

JS in `app.js`: `checkForUpdates()` runs on settings page load.
`startUpdate()` posts to `/api/update/start`, swaps the button for a
"Updating, the box will restart shortly…" message.

## Error handling

- Offline: check returns `error: "offline"`, UI shows "Couldn't check
  for updates" with retry.
- Local divergence (manual edits): check still works, but update
  attempt fails — UI surfaces the error from journald.
- Sudoers missing: API returns 500 with hint to re-run install.sh.

## Out of scope (YAGNI)

- Release notes / changelog rendering.
- Rollback button.
- Tracking branches other than `main`.
- Update scheduling.

## Testing

- Manual: trigger check on a current and a stale checkout.
- Verify sudoers drop-in is installed and update succeeds without
  password.
- Verify update survives Flask restarting (transient unit detaches).
