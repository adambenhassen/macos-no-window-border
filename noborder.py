#!/Applications/Xcode.app/Contents/Developer/usr/bin/python3
"""
noborder: remove the 1px gray outline (and shadow) from every normal macOS window.

The outline is drawn by WindowServer as part of the shadow. It goes away when a window
carries WindowServer tag bit 3 (what NSWindow.hasShadow = NO sets). WindowServer only
accepts that tag from the window's owner or from Dock's privileged connection, so this
daemon keeps one lldb session attached to Dock and, whenever `winscan --watch` reports
a normal window that still has a shadow, briefly interrupts Dock, calls SLSSetWindowTags
from inside it, and resumes. Dock is paused for a few milliseconds per batch.

Requirements: SIP disabled (task_for_pid on Dock), Xcode (its LLDB Python module).
Usage: noborder.py [--once]   (--once: tag current windows, detach, exit)
"""
import os
import signal
import subprocess
import sys
import time

XCODE = subprocess.run(["xcode-select", "-p"], capture_output=True, text=True, check=True).stdout.strip()
sys.path.insert(0, os.path.join(os.path.dirname(XCODE), "SharedFrameworks/LLDB.framework/Resources/Python"))
import lldb  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
WINSCAN = os.path.join(HERE, "winscan")
NOSHADOW_TAG = 1 << 3
RETRY_BASE_S = 2.0      # back off windows whose app keeps restoring its shadow
RETRY_MAX_S = 120.0


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def dock_pid():
    out = subprocess.run(["pgrep", "-x", "Dock"], capture_output=True, text=True).stdout.split()
    return int(out[0]) if out else None


def tag_expr(wids):
    calls = "".join(
        f"r |= (int)SLSSetWindowTags(c, (unsigned int){w}, &t, 64);" for w in wids
    )
    return f"({{ unsigned long long t = {NOSHADOW_TAG}ULL; int c = (int)SLSMainConnectionID(); int r = 0; {calls} r; }})"


class Dock:
    """One lldb session attached to Dock, normally running (async)."""

    def __init__(self):
        self.debugger = lldb.SBDebugger.Create()
        self.debugger.SetAsync(True)
        self.listener = self.debugger.GetListener()
        self.process = None

    def attach(self):
        pid = dock_pid()
        if pid is None:
            return False
        target = self.debugger.CreateTarget("")
        err = lldb.SBError()
        self.process = target.AttachToProcessWithID(self.listener, pid, err)
        if err.Fail() or not self.process.IsValid():
            log(f"attach to Dock pid {pid} failed: {err}")
            self.process = None
            return False
        self.wait_stopped()
        self.process.Continue()
        log(f"attached to Dock pid {pid}")
        return True

    def drain(self):
        ev = lldb.SBEvent()
        while self.listener.GetNextEvent(ev):
            pass

    def wait_stopped(self, timeout=5.0):
        ev = lldb.SBEvent()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.listener.WaitForEvent(1, ev) and lldb.SBProcess.EventIsProcessEvent(ev):
                if lldb.SBProcess.GetStateFromEvent(ev) == lldb.eStateStopped:
                    return True
            if self.process.GetState() == lldb.eStateStopped:
                return True
        return False

    def alive(self):
        self.drain()
        state = self.process.GetState() if self.process else lldb.eStateInvalid
        if state == lldb.eStateRunning:
            return True
        if state == lldb.eStateStopped:
            # Stopped without us asking: a signal or crash. Get out of the way.
            log("Dock stopped on its own; detaching")
        elif self.process:
            log(f"Dock process state {lldb.SBDebugger.StateAsCString(state)}; reattaching")
        self.detach()
        return False

    def tag(self, wids):
        self.process.Stop()
        if not self.wait_stopped():
            log("interrupt timed out")
            return False
        frame = self.process.GetSelectedThread().GetSelectedFrame()
        val = frame.EvaluateExpression(tag_expr(wids))
        ok = val.IsValid() and val.GetError().Success()
        rc = val.GetValueAsSigned() if ok else None
        self.process.Continue()
        if not ok:
            log(f"expression failed: {val.GetError()}")
        elif rc != 0:
            log(f"SLSSetWindowTags returned {rc} for {wids}")
        return ok and rc == 0

    def detach(self):
        if self.process and self.process.IsValid():
            self.process.Detach()
        self.process = None
        self.debugger.DeleteTarget(self.debugger.GetSelectedTarget())


def main():
    once = "--once" in sys.argv
    dock = Dock()
    stop = {"flag": False}

    def on_signal(signum, _frame):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    if once:
        wids = [line.split("\t")[0] for line in subprocess.run([WINSCAN], capture_output=True, text=True).stdout.splitlines()]
        if not wids:
            log("nothing to tag")
        elif dock.attach():
            log(f"tagging {len(wids)} window(s): {' '.join(wids)}")
            dock.tag(wids)
            dock.detach()
        return

    retry_at = {}
    while not stop["flag"]:
        if dock.process is None and not dock.attach():
            time.sleep(2)
            continue
        scanner = subprocess.Popen([WINSCAN, "--watch"], stdout=subprocess.PIPE, text=True)
        try:
            while not stop["flag"]:
                line = scanner.stdout.readline()
                if line == "":
                    log("winscan exited; restarting")
                    break
                if not dock.alive():
                    break
                now = time.time()
                wids = [w for w in line.split() if retry_at.get(w, (0, 0))[0] <= now]
                if not wids:
                    continue
                for w in wids:
                    _, delay = retry_at.get(w, (0, RETRY_BASE_S / 2))
                    delay = min(delay * 2, RETRY_MAX_S)
                    retry_at[w] = (now + delay, delay)
                log(f"tagging {' '.join(wids)}")
                dock.tag(wids)
                if len(retry_at) > 4096:
                    retry_at = {w: v for w, v in retry_at.items() if v[0] > now}
        finally:
            scanner.kill()
            scanner.wait()
    dock.detach()
    log("exiting")


if __name__ == "__main__":
    main()
