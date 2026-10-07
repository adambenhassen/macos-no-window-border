# macos-no-window-border

NoBorder makes maximized windows edge to edge on macOS: no 1px gray outline (and drop shadow),
square corners, and no light rim along the titlebar edge. Windows that don't fill their
screen's usable area keep the normal macOS look, and a window that stops being maximized gets
back exactly what NoBorder changed.

Website: https://adambenhassen.github.io/macos-no-window-border/

## How it works

- **Outline and shadow:** WindowServer draws the outline as part of the window shadow. Both
  disappear when a window carries WindowServer tag bit 3, the tag `NSWindow.hasShadow = NO`
  sets. WindowServer only accepts that tag from the window's owner or from Dock's privileged
  connection, so the daemon keeps one lldb session attached to Dock and calls
  `SLSSetWindowTags` / `SLSClearWindowTags` from inside it. Dock pauses for a few milliseconds.
- **Corners and rim:** these come from AppKit inside each app, so only that app can change
  them. The daemon attaches lldb to the owning app, queues two calls on the app's main run
  loop, and detaches:
  - `-[NSWindow _setCornerRadius:0.01]` to square the corners (`0` restores the default)
  - `drawsDecorationView = NO` on the titlebar container (`YES` restores the rim; it also
    hides and restores the titlebar separator)

  The calls are queued instead of run at the pause point, because running AppKit code
  wherever the app happened to stop can re-enter it and crash it.
- **Which windows:** `winscan` lists normal windows every 250 ms with their shadow state and
  whether they fill their screen's `NSScreen.visibleFrame` within 2 pt. A window must stay
  maximized (or not) for 0.5 s before anything changes.

Costs and limits:

- An app freezes for ~1 s each time one of its windows becomes or stops being maximized (~3 s
  for the first app after the daemon starts, while lldb parses the shared cache).
- A starting or busy app's windows are squared once the app is idle. The daemon checks first
  and runs nothing inside a busy app.
- Only AppKit windows (including Chromium and Electron apps) change corners. Others keep them.
- Uses private AppKit and SkyLight APIs. If a macOS update removes the AppKit methods, the
  daemon skips that step instead of crashing the app.

## Requirements

- macOS 14 or later (tested on macOS 15).
- SIP disabled (needed to attach to Dock and to apps). No boot-args, no reboot.
- Xcode installed (the LLDB Python module ships with it).

## Usage

```sh
make install     # build NoBorder.app and copy it to /Applications
open /Applications/NoBorder.app
```

The menu bar icon shows the status and has Enabled, Launch at Login and Quit. Turning it off
or quitting restores every window NoBorder changed. While it restores, the menu shows "Stopping: restoring windows…".

Logs: `~/Library/Logs/macos-no-window-border.log`.

Upgrading from the LaunchAgent version: remove the old agent first, or two daemons will fight
over the same windows.

```sh
launchctl bootout gui/$(id -u)/local.macos-no-window-border
rm ~/Library/LaunchAgents/local.macos-no-window-border.plist
```

Windows changed by the old version (which changed every window) aren't tracked by NoBorder;
restart those apps, or reopen their windows, once.

Development:

```sh
make test                          # Python and Swift unit tests
make testtools && tests/e2e.sh     # end-to-end check against a test app (stop NoBorder first)
make testtools && tests/idle.sh    # busy-app check against a test app (NoBorder may run)
./noborder.py --pids 123           # run the daemon in a terminal, only for pid 123's windows
```

## Files

- `winscan.m`: window scanner (shadow state, maximized flag)
- `windowstate.py`: decides which windows to change or restore
- `noborder.py`: daemon driving lldb into Dock and apps
- `app/`: NoBorder menu bar app (SwiftPM)
- `tests/`: unit tests, test app, end-to-end script
