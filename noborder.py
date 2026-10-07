#!/Applications/Xcode.app/Contents/Developer/usr/bin/python3
"""
noborder: remove the 1px gray outline (and shadow), the rounded corners and the titlebar
rim highlight from every normal macOS window.

The outline is drawn by WindowServer as part of the shadow. It goes away when a window
carries WindowServer tag bit 3 (what NSWindow.hasShadow = NO sets). WindowServer only
accepts that tag from the window's owner or from Dock's privileged connection, so this
daemon keeps one lldb session attached to Dock and, whenever `winscan --watch` reports
a normal window that still has a shadow, briefly interrupts Dock, calls SLSSetWindowTags
from inside it, and resumes. Dock is paused for a few milliseconds per batch.

The rounded corners are a mask AppKit hands WindowServer for each window, and the light
rim along the titlebar edge is drawn by AppKit's titlebar decoration view; only the owning
app can change either. For every new window the daemon briefly attaches to its app and
queues -[NSWindow _setCornerRadius:] with a sub-pixel radius, plus drawsDecorationView = NO
on the titlebar container, on the app's main run loop. The app is paused for ~1 s per
batch (~3 s on the first attach, while lldb parses the shared cache). Non-AppKit windows
keep their corners.

Requirements: SIP disabled (task_for_pid on Dock and apps), Xcode (its LLDB Python module).
Usage: noborder.py [--once]   (--once: fix current windows, detach, exit)
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
CORNER_RADIUS = 0.01    # AppKit treats 0 as "use the default radius"; sub-pixel draws square


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


def queue_call(target, selector, args):
    """Expression code that queues [target selector args...] on the main run loop."""
    sets = "".join(f" msg3(inv, sel(\"setArgument:atIndex:\"), {a}, {i + 2}L);" for i, a in enumerate(args))
    return (
        f"{{ void *inv = msg(cls(\"NSInvocation\"), sel(\"invocationWithMethodSignature:\"),"
        f" msg({target}, sel(\"methodSignatureForSelector:\"), {selector}));"
        f" msg(inv, sel(\"setSelector:\"), {selector}); msg(inv, sel(\"setTarget:\"), {target});{sets}"
        " msg(inv, sel(\"retainArguments\"), 0);"
        " post(inv, sel(\"performSelectorOnMainThread:withObject:waitUntilDone:\"), sel(\"invoke\"), 0, 0); }"
    )


def corner_expr(wids):
    # Running AppKit code at an arbitrary pause point can re-enter the app and crash it, so the
    # expression only queues calls on the main run loop via NSInvocation:
    #   [window _setCornerRadius:]                                   square corners
    #   [window setValue:@NO forKeyPath:@"_titlebarContainerView.drawsDecorationView"]
    #                                                                drop the titlebar rim highlight
    # Plain C (objc_msgSend casts) compiles several times faster than an ObjC expression.
    calls = "".join(
        f"w = msg(a, sel(\"windowWithWindowNumber:\"), (void *){w}L);"
        f" if (w) {{ {queue_call('w', 'cr', ['&r'])}"
        f" if (rim) {queue_call('w', 'kvc', ['&no', '&path'])} n++; }}"
        for w in wids
    )
    return (
        "({ void *(*sel)(const char *) = (void *(*)(const char *))sel_registerName;"
        " void *(*cls)(const char *) = (void *(*)(const char *))objc_getClass;"
        " void *(*msg)(void *, void *, void *) = (void *(*)(void *, void *, void *))objc_msgSend;"
        " void (*msg3)(void *, void *, void *, long) = (void (*)(void *, void *, void *, long))objc_msgSend;"
        " void (*post)(void *, void *, void *, void *, unsigned char) ="
        " (void (*)(void *, void *, void *, void *, unsigned char))objc_msgSend;"
        " unsigned char (*responds)(void *, void *) = (unsigned char (*)(void *, void *))class_respondsToSelector;"
        f" void *a = *(void **)&NSApp; void *cr = sel(\"_setCornerRadius:\"); double r = {CORNER_RADIUS};"
        " void *kvc = sel(\"setValue:forKeyPath:\");"
        " int rim = responds(cls(\"NSWindow\"), sel(\"_titlebarContainerView\"))"
        " && responds(cls(\"NSTitlebarContainerView\"), sel(\"setDrawsDecorationView:\"));"
        " void *no = msg(cls(\"NSNumber\"), sel(\"numberWithBool:\"), 0);"
        " void *path = msg(cls(\"NSString\"), sel(\"stringWithUTF8String:\"),"
        " (void *)\"_titlebarContainerView.drawsDecorationView\");"
        " void *w = 0; int n = -1;"
        f" if (a && responds(cls(\"NSWindow\"), cr)) {{ n = 0; {calls} }} n; }})"
    )


class Apps:
    """Short attaches to app processes. Reusing one debugger keeps lldb's parsed copy of the
    shared cache, which cuts each attach from ~3 s to under 1 s."""

    def __init__(self):
        self.debugger = lldb.SBDebugger.Create()
        self.debugger.SetAsync(False)

    def square(self, pid, wids):
        target = self.debugger.CreateTarget("")
        err = lldb.SBError()
        process = target.AttachToProcessWithID(self.debugger.GetListener(), pid, err)
        if err.Fail() or not process.IsValid():
            log(f"attach to pid {pid} failed: {err}")
            self.debugger.DeleteTarget(target)
            return False
        try:
            thread = process.GetThreadAtIndex(0)  # main thread; AppKit must be called there
            process.SetSelectedThread(thread)
            opts = lldb.SBExpressionOptions()
            opts.SetLanguage(lldb.eLanguageTypeC)
            opts.SetTryAllThreads(False)
            opts.SetTimeoutInMicroSeconds(2_000_000)
            val = thread.GetFrameAtIndex(0).EvaluateExpression(corner_expr(wids), opts)
            ok = val.IsValid() and val.GetError().Success()
            n = val.GetValueAsSigned() if ok else None
        finally:
            process.Detach()
            self.debugger.DeleteTarget(target)
        if not ok:
            log(f"pid {pid}: expression failed: {val.GetError()}")
        elif n < 0:
            log(f"pid {pid}: not an AppKit app; corners left as is")
        elif n != len(wids):
            log(f"pid {pid}: squared {n} of {len(wids)} window(s)")
        return ok and n == len(wids)


def by_pid(windows):
    groups = {}
    for wid, pid in windows:
        groups.setdefault(int(pid), []).append(wid)
    return groups


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
        self.wait_state(lldb.eStateStopped)
        self.process.Continue()
        self.wait_state(lldb.eStateRunning)  # a Stop() sent before Dock resumes is lost
        log(f"attached to Dock pid {pid}")
        return True

    def drain(self):
        ev = lldb.SBEvent()
        while self.listener.GetNextEvent(ev):
            pass

    def wait_state(self, state, timeout=5.0):
        ev = lldb.SBEvent()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.listener.WaitForEvent(1, ev) and lldb.SBProcess.EventIsProcessEvent(ev):
                if lldb.SBProcess.GetStateFromEvent(ev) == state:
                    return True
            if self.process.GetState() == state:
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
        if not self.wait_state(lldb.eStateStopped):
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
    apps = Apps()
    stop = {"flag": False}

    def on_signal(signum, _frame):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    if once:
        rows = [line.split("\t") for line in subprocess.run([WINSCAN, "--all"], capture_output=True, text=True).stdout.splitlines()]
        for pid, pwids in by_pid((r[0], r[1]) for r in rows).items():
            log(f"squaring pid {pid}: {' '.join(pwids)}")
            apps.square(pid, pwids)
        time.sleep(0.5)  # squaring restores the shadow once the app runs the queued call; tag after
        wids = [line.split("\t")[0] for line in subprocess.run([WINSCAN], capture_output=True, text=True).stdout.splitlines()]
        if not wids:
            log("nothing to tag")
        elif dock.attach():
            log(f"tagging {len(wids)} window(s): {' '.join(wids)}")
            dock.tag(wids)
            dock.detach()
        return

    retry_at = {}
    squared = set()  # wids whose corners were handled (or failed); attaching again won't help
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
                windows = [t.split(":") for t in line.split()]
                wids = [w for w, _, shadow in windows if shadow == "1" and retry_at.get(w, (0, 0))[0] <= now]
                if wids:
                    for w in wids:
                        _, delay = retry_at.get(w, (0, RETRY_BASE_S / 2))
                        delay = min(delay * 2, RETRY_MAX_S)
                        retry_at[w] = (now + delay, delay)
                    log(f"tagging {' '.join(wids)}")
                    dock.tag(wids)
                    if len(retry_at) > 4096:
                        retry_at = {w: v for w, v in retry_at.items() if v[0] > now}
                skip = {os.getpid(), dock.process.GetProcessID()}
                fresh = [(w, pid) for w, pid, _ in windows if w not in squared and int(pid) not in skip]
                for pid, pwids in by_pid(fresh).items():
                    squared.update(pwids)
                    log(f"squaring pid {pid}: {' '.join(pwids)}")
                    apps.square(pid, pwids)
                    for w in pwids:  # AppKit restores the shadow once; retag on the next scan
                        retry_at.pop(w, None)
                if len(squared) > 4096:
                    squared &= {w for w, _, _ in windows}
        finally:
            scanner.kill()
            scanner.wait()
    dock.detach()
    log("exiting")


if __name__ == "__main__":
    main()
