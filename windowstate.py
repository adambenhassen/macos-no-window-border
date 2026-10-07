"""
windowstate: decide which windows noborder changes. Pure logic with no lldb, so it can be
unit tested. noborder.py feeds it each `winscan --watch` line and executes the Actions.
"""
from dataclasses import dataclass, field
from typing import Optional, Tuple

APPLY_SETTLE_S = 2.0    # a window must stay maximized this long before it is changed
RESTORE_SETTLE_S = 0.5  # and stay un-maximized this long before it is restored
RETRY_BASE_S = 2.0      # back off windows whose app keeps restoring its shadow
RETRY_MAX_S = 120.0
BUSY_BASE_S = 1.0       # back off windows whose app was busy (main thread not idle)
BUSY_CHECKS = 3         # busy results before giving up until the window changes
MAX_RECORDS = 4096      # applied records kept for windows not currently on screen


@dataclass(frozen=True)
class Window:
    wid: int
    pid: int
    shadow: bool
    maximized: bool


@dataclass
class Actions:
    apply: dict = field(default_factory=dict)    # pid -> [wid]: square corners, drop the rim
    restore: dict = field(default_factory=dict)  # pid -> [wid]: default corners, rim back
    tag: list = field(default_factory=list)      # wids to give the no-shadow tag (via Dock)
    untag: list = field(default_factory=list)    # wids to clear the no-shadow tag (via Dock)

    def empty(self):
        return not (self.apply or self.restore or self.tag or self.untag)


def parse_watch(line):
    """Parse one `winscan --watch` line of <wid>:<pid>:<shadow>:<maximized> tokens."""
    windows = []
    for token in line.split():
        wid, pid, shadow, maximized = token.split(":")
        windows.append(Window(int(wid), int(pid), shadow == "1", maximized == "1"))
    return windows


def latest_line(buffer: bytes) -> Tuple[Optional[str], bytes]:
    """Split buffered `winscan --watch` output into its newest complete line (None if there is
    none yet) and the incomplete rest, which the caller prepends to its next read."""
    end = buffer.rfind(b"\n")
    if end < 0:
        return None, buffer
    start = buffer.rfind(b"\n", 0, end) + 1
    return buffer[start:end].decode(), buffer[end + 1:]


class Tracker:
    """Remembers which windows noborder changed, so it only ever restores its own changes."""

    def __init__(self, apply_settle_s=APPLY_SETTLE_S, restore_settle_s=RESTORE_SETTLE_S):
        self.apply_settle_s = apply_settle_s
        self.restore_settle_s = restore_settle_s
        self.applied = {}      # wid -> pid
        self.had_shadow = {}   # wid -> untag on restore: shadow was on when applied, or we tagged
        self.pending = {}      # wid -> (target maximized state, first seen at)
        self.retry = {}        # wid -> (next tag allowed at, current delay)
        self.held = {}         # wid -> (act again at, busy results so far) after the app was busy
        self.gave_up = {}      # wid -> maximized state it was busy in; wait for it to change

    def update(self, windows, now, skip_pids=()):
        """skip_pids: apps to leave alone this scan (ours, Dock, apps still starting up). Their
        windows don't settle until they are no longer skipped."""
        acts = Actions()
        seen = set()
        for w in windows:
            if w.pid in skip_pids:
                continue
            seen.add(w.wid)
            if self.held.get(w.wid, (0.0,))[0] > now:
                continue
            if self.gave_up.get(w.wid, not w.maximized) == w.maximized:
                continue
            self.gave_up.pop(w.wid, None)
            applied = w.wid in self.applied
            if w.maximized == applied:
                self.pending.pop(w.wid, None)
                self.held.pop(w.wid, None)  # the busy action is done or no longer needed
                if applied and w.shadow:
                    self._tag(w.wid, now, acts)
                continue
            target, since = self.pending.get(w.wid, (None, now))
            if target != w.maximized:
                self.pending[w.wid] = (w.maximized, now)
                continue
            if now - since < (self.apply_settle_s if w.maximized else self.restore_settle_s):
                continue
            del self.pending[w.wid]
            if w.maximized:
                self.applied[w.wid] = w.pid
                self.had_shadow[w.wid] = w.shadow
                self.retry.pop(w.wid, None)
                acts.apply.setdefault(w.pid, []).append(w.wid)
            else:
                self._forget(w.wid, acts)
        for wid in list(self.pending):
            if wid not in seen:
                del self.pending[wid]
        for wid in [wid for wid, (at, _) in self.held.items() if wid not in seen and at <= now]:
            del self.held[wid]
        for wid in [wid for wid in self.gave_up if wid not in seen]:
            del self.gave_up[wid]  # disappeared: try again when it is back
        if len(self.applied) > MAX_RECORDS:
            for wid in [wid for wid in self.applied if wid not in seen]:
                del self.applied[wid]
                self.had_shadow.pop(wid, None)
                self.retry.pop(wid, None)
        return acts

    def restore_all(self):
        acts = Actions()
        for wid in list(self.applied):
            self._forget(wid, acts)
        self.pending.clear()
        self.held.clear()
        self.gave_up.clear()
        return acts

    def hold(self, pid, wids, now, restoring):
        """The app was busy, so the apply or restore that update() emitted for wids did not run.
        Undo its bookkeeping and emit nothing for these windows until a per-window backoff
        (1, 2 s) has passed. On the BUSY_CHECKS-th busy result in a row, give up on a window until
        its maximized state changes or it disappears. Returns (shortest delay, or None if all
        windows were given up; [given up wids])."""
        delays, given_up = [], []
        for wid in wids:
            if restoring:
                self.applied[wid] = pid  # still squared; restore again later (the untag is done)
            else:
                self.applied.pop(wid, None)
                self.had_shadow.pop(wid, None)
            count = self.held.pop(wid, (0.0, 0))[1] + 1
            if count >= BUSY_CHECKS:
                self.gave_up[wid] = not restoring
                given_up.append(wid)
                continue
            delay = BUSY_BASE_S * 2 ** (count - 1)
            self.held[wid] = (now + delay, count)
            delays.append(delay)
        return min(delays, default=None), given_up

    def _tag(self, wid, now, acts):
        next_at, delay = self.retry.get(wid, (0.0, RETRY_BASE_S / 2))
        if next_at > now:
            return
        delay = min(delay * 2, RETRY_MAX_S)
        self.retry[wid] = (now + delay, delay)
        self.had_shadow[wid] = True  # untag on restore: this tag is ours
        acts.tag.append(wid)

    def _forget(self, wid, acts):
        pid = self.applied.pop(wid)
        acts.restore.setdefault(pid, []).append(wid)
        if self.had_shadow.pop(wid, False):
            acts.untag.append(wid)
        self.retry.pop(wid, None)
