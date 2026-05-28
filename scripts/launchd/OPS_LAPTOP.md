# Running Deleveraging Watch 24/7 on the laptop

This guide is the prevent-sleep + run-on-boot recipe for macOS. DESIGN.md §14
specifies the constraint ("single user, single laptop, must survive overnight
on its own"); this file is the literal commands to make that work.

## 1. Install the LaunchAgents

Two plists ship under `scripts/launchd/`:

| File | Purpose |
|---|---|
| `com.user.deleveraging-watch.plist`     | Boots the Flask + scheduler process at login; relaunches on crash. |
| `com.user.deleveraging-caffeinate.plist`| Holds an idle-sleep assertion so background jobs keep firing overnight. |

```bash
# 1) Patch the placeholders with your actual paths.
PYBIN="$(realpath "$VIRTUAL_ENV/bin/python")"     # or wherever your venv lives
WORKDIR="$(realpath ./Freecss)"
sed -i '' "s|PYTHON_PATH_PLACEHOLDER|$PYBIN|;
          s|FREECSS_PATH_PLACEHOLDER|$WORKDIR|;
          s|HOME_PATH_PLACEHOLDER|$HOME|" \
  scripts/launchd/com.user.deleveraging-watch.plist

# 2) Copy both into LaunchAgents and load them.
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/deleveraging-watch"
cp scripts/launchd/com.user.deleveraging-watch.plist        ~/Library/LaunchAgents/
cp scripts/launchd/com.user.deleveraging-caffeinate.plist   ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.user.deleveraging-watch.plist
launchctl load -w ~/Library/LaunchAgents/com.user.deleveraging-caffeinate.plist
```

## 2. Verify

```bash
launchctl list | grep deleveraging
# Both labels should appear; PID column non-zero means running.

curl -s http://127.0.0.1:5001/api/health | jq .
tail -f ~/Library/Logs/deleveraging-watch/server.log
```

## 3. Sleep settings — the non-obvious ones

The `caffeinate -i` LaunchAgent holds an **idle-sleep assertion**. That keeps
the system awake even when the user is away, *as long as the laptop is on
power AND either the lid is open OR an external display is connected*.

If you run lid-closed on battery, macOS will still sleep — that's a kernel-
level rule `caffeinate` can't override. Options:

- **Plug in.** Easiest. AC + caffeinate keeps things alive lid-closed.
- **Use an external display** (even a tiny one). Same effect lid-closed.
- **Disable lid-sleep entirely** (Energy Saver → "Prevent automatic
  sleeping when the display is off"). Most aggressive; battery doesn't last.

WiFi disconnects on sleep are handled by APScheduler's catch-up + the
quote-stream supervisor — see §14 in DESIGN.md.

## 4. Reload / stop / uninstall

```bash
# Reload after editing the plist:
launchctl unload  ~/Library/LaunchAgents/com.user.deleveraging-watch.plist
launchctl load -w ~/Library/LaunchAgents/com.user.deleveraging-watch.plist

# Stop both for a maintenance window:
launchctl unload ~/Library/LaunchAgents/com.user.deleveraging-watch.plist
launchctl unload ~/Library/LaunchAgents/com.user.deleveraging-caffeinate.plist

# Uninstall entirely:
launchctl unload ~/Library/LaunchAgents/com.user.deleveraging-watch.plist
launchctl unload ~/Library/LaunchAgents/com.user.deleveraging-caffeinate.plist
rm ~/Library/LaunchAgents/com.user.deleveraging-{watch,caffeinate}.plist
```

## 5. Diagnostic checklist

| Symptom | First place to look |
|---|---|
| Process not running          | `launchctl list \| grep deleveraging` → if absent, `launchctl load` it. |
| Crash-loop                   | `tail ~/Library/Logs/deleveraging-watch/server.log` — last 200 lines. |
| No ticks overnight           | `curl 127.0.0.1:5001/api/health` → `feed.last_tick_age_s`; if stale, WS reconnect supervisor should have retried (check log). |
| No morning digest            | `pmset -g log \| grep -i sleep` → laptop slept past 08:00 ET; check the caffeinate agent. |
| 5001 already in use          | macOS AirPlay Receiver squats 5000 (that's why we moved to 5001); something else owns it now. `lsof -nP -iTCP:5001 -sTCP:LISTEN` to identify. |
