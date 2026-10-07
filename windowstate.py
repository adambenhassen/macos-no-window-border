"""
windowstate: decide which windows noborder changes. Pure logic with no lldb, so it can be
unit tested. noborder.py feeds it each `winscan --watch` line and executes the Actions.
"""
from dataclasses import dataclass, field
from typing import Optional, Tuple

SETTLE_S = 0.5          # a window's maximized state must hold this long before acting
RETRY_BASE_S = 2.0      # back off windows whose app keeps restoring its shadow
RETRY_MAX_S = 120.0
BUSY_BASE_S = 1.0       # back off windows whose app was busy (main thread not idle)
BUSY_MAX_S = 30.0
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

    def __init__(self, settle_s=SETTLE_S):
        self.settle_s = settle_s
        self.applied = {}      # wid -> pid
        self.had_shadow = {}   # wid -> untag on restore: shadow was on when applied, or we tagged
        self.pending = {}      # wid -> (target maximized state, first seen at)
        self.retry = {}        # wid -> (next tag allowed at, current delay)
        self.held = {}         # wid -> (act again at, current delay) after the app was busy

    def update(self, windows, now, skip_pids=()):
        acts = Actions()
        seen = set()
        for w in windows:
            if w.pid in skip_pids:
                continue
            seen.add(w.wid)
            if self.held.get(w.wid, (0.0,))[0] > now:
                continue
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
            if now - since < self.settle_s:
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
        return acts

    def hold(self, pid, wids, now, restoring):
        """The app was busy, so the apply or restore that update() emitted for wids did not run.
        Undo its bookkeeping and emit nothing for these windows until a per-window backoff
        (1, 2, 4... s, capped at BUSY_MAX_S) has passed. Returns the shortest delay."""
        delays = []
        for wid in wids:
            if restoring:
                self.applied[wid] = pid  # still squared; restore again later (the untag is done)
            else:
                self.applied.pop(wid, None)
                self.had_shadow.pop(wid, None)
            delay = min(self.held.get(wid, (0.0, BUSY_BASE_S / 2))[1] * 2, BUSY_MAX_S)
            self.held[wid] = (now + delay, delay)
            delays.append(delay)
        return min(delays)

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
