# macos-no-window-border

Removes the 1px gray outline (and the drop shadow), the rounded corners and the titlebar
rim highlight from every normal window on macOS.

## How it works

WindowServer draws the outline as part of the window shadow. Both disappear when a window
carries WindowServer tag bit 3, the tag `NSWindow.hasShadow = NO` sets. WindowServer only
accepts that tag from the window's owner or from Dock's privileged connection.

- `winscan` lists on-screen layer-0 windows and reads their shadow tag (reading works from any process).
- `noborder.py` keeps one lldb session attached to Dock. When `winscan --watch` reports a
  window that still has a shadow, it interrupts Dock, calls `SLSSetWindowTags` from inside
  it, and resumes. Dock pauses for a few milliseconds per batch. New windows lose their
  border within ~250 ms of appearing.

Windows whose app keeps restoring its shadow are retried with exponential backoff (2 s to 2 min).

Rounded corners and the light rim along the titlebar edge come from AppKit inside each app,
so only that app can change them. For every new window, `noborder.py` attaches lldb to the
owning app, queues two calls on the app's main run loop, and detaches:

- `-[NSWindow _setCornerRadius:0.01]` (0 means "default radius"; sub-pixel draws square)
- `drawsDecorationView = NO` on the titlebar container (also hides the titlebar separator)

The calls are queued, not run at the pause point, because running AppKit code wherever the
app happened to stop can re-enter it and crash it.

Costs and limits:

- The app freezes for ~1 s each time it opens a window (~3 s for the first app after the
  daemon starts, while lldb parses the shared cache).
- Only AppKit windows (including Chromium and Electron apps). Others keep their corners.
- Uses private AppKit methods. If a macOS update removes them, the daemon skips the step.

## Requirements

- Apple Silicon or Intel, macOS 15 tested.
- SIP disabled (needed to attach to Dock and to apps). No boot-args, no reboot.
- Xcode installed (the LLDB Python module ships with it).

## Usage

```sh
make                 # build winscan
./noborder.py --once # fix everything visible right now, then exit
./noborder.py        # run in the foreground
make install         # LaunchAgent: start at login, keep running
make status
make uninstall
```

Logs: `~/Library/Logs/macos-no-window-border.log`.

To restore a window's shadow, corners and rim, reopen the window (or restart the app)
after `make uninstall`.

## Files

- `winscan.c` — window/tag scanner
- `noborder.py` — daemon driving lldb into Dock and apps
- `launchagent.plist` — template installed by `make install`
