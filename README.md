# macos-no-window-border

Removes the 1px gray outline (and the drop shadow) from every normal window on macOS.

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

## Requirements

- Apple Silicon or Intel, macOS 15 tested.
- SIP disabled (needed to attach to Dock). No boot-args, no reboot.
- Xcode installed (the LLDB Python module ships with it).

## Usage

```sh
make                 # build winscan
./noborder.py --once # tag everything visible right now, then exit
./noborder.py        # run in the foreground
make install         # LaunchAgent: start at login, keep running
make status
make uninstall
```

Logs: `~/Library/Logs/macos-no-window-border.log`.

To restore a window's shadow, the app must call `hasShadow = YES` again, or simply
reopen the window after `make uninstall`.

## Files

- `winscan.c` — window/tag scanner
- `noborder.py` — daemon driving lldb into Dock
- `launchagent.plist` — template installed by `make install`
