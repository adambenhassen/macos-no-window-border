#!/Applications/Xcode.app/Contents/Developer/usr/bin/python3
"""
noborder: make maximized macOS windows edge to edge: no 1px gray outline (and shadow), square
corners, no titlebar rim highlight. Other windows keep the normal look, and a window that stops
being maximized gets back exactly what noborder changed.

The outline is drawn by WindowServer as part of the shadow. It goes away when a window
carries WindowServer tag bit 3 (what NSWindow.hasShadow = NO sets). WindowServer only
accepts that tag from the window's owner or from Dock's privileged connection, so this
daemon keeps one lldb session attached to Dock and briefly interrupts it to call
SLSSetWindowTags / SLSClearWindowTags from inside. Dock is paused for a few milliseconds.

The rounded corners are a mask AppKit hands WindowServer for each window, and the light
rim along the titlebar edge is drawn by AppKit's titlebar decoration view; only the owning
app can change either. When a window becomes (or stops being) maximized, the daemon briefly
attaches to its app and queues -[NSWindow _setCornerRadius:] plus drawsDecorationView on the
titlebar container on the app's main run loop. The app is paused for ~1 s per batch (~3 s on
the first attach, while lldb parses the shared cache). Non-AppKit windows keep their corners.

Requirements: SIP disabled (task_for_pid on Dock and apps), Xcode (its LLDB Python module).
Usage: noborder.py [--pids PID,PID...]   (--pids: only manage these apps' windows; for testing)
Prints `status: ...` lines for NoBorder.app. SIGTERM, SIGINT or the parent process exiting
restores every changed window, then exits.
"""
import os
import select
import signal
import subprocess
import sys
import time

import windowstate

HERE = os.path.dirname(os.path.abspath(__file__))
WINSCAN = os.path.join(HERE, "winscan")
NOSHADOW_TAG = 1 << 3
CORNER_RADIUS = 0.01    # AppKit treats 0 as "use the default radius"; sub-pixel draws square
lldb = None             # LLDB Python module, loaded by load_lldb()


def emit(text):
    try:
        print(text, flush=True)
    except OSError:
        # The reader is gone (NoBorder.app quit; Python ignores SIGPIPE, so the write raises
        # BrokenPipeError). Send stdout to /dev/null from now on, including the unwritten
        # buffer and the exit flush, so restoring the windows still completes.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)


def log(msg):
    emit(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}")


def status(msg):
    emit(f"status: {msg}")


def sip_blocks_debugging():
    out = subprocess.run(["csrutil", "status"], capture_output=True, text=True).stdout
    return "status: disabled" not in out and "Debugging Restrictions: disabled" not in out


def load_lldb():
    try:
        xcode = subprocess.run(["xcode-select", "-p"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    sys.path.insert(0, os.path.join(os.path.dirname(xcode), "SharedFrameworks/LLDB.framework/Resources/Python"))
    try:
        import lldb as module
    except ImportError:
        return None
    return module


def dock_pid():
    out = subprocess.run(["pgrep", "-x", "Dock"], capture_output=True, text=True).stdout.split()
    return int(out[0]) if out else None


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def tag_expr(wids, function):
    calls = "".join(
        f"r |= (int){function}(c, (unsigned int){w}, &t, 64);" for w in wids
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


def window_expr(wids, apply):
    # Running AppKit code at an arbitrary pause point can re-enter the app and crash it, so the
    # expression only queues calls on the main run loop via NSInvocation:
    #   [window _setCornerRadius:]          0.01 squares the corners; 0 restores the default
    #   [window setValue:@NO/@YES forKeyPath:@"_titlebarContainerView.drawsDecorationView"]
    #                                       drops or restores the titlebar rim highlight
    # Plain C (objc_msgSend casts) compiles several times faster than an ObjC expression.
    radius = CORNER_RADIUS if apply else 0.0
    decoration = 0 if apply else 1
    calls = "".join(
        f"w = msg(a, sel(\"windowWithWindowNumber:\"), (void *){w}L);"
        f" if (w) {{ {queue_call('w', 'cr', ['&r'])}"
        f" if (rim) {queue_call('w', 'kvc', ['&flag', '&path'])} n++; }}"
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
        f" void *a = *(void **)&NSApp; void *cr = sel(\"_setCornerRadius:\"); double r = {radius};"
        " void *kvc = sel(\"setValue:forKeyPath:\");"
        " int rim = responds(cls(\"NSWindow\"), sel(\"_titlebarContainerView\"))"
        " && responds(cls(\"NSTitlebarContainerView\"), sel(\"setDrawsDecorationView:\"));"
        f" void *flag = msg(cls(\"NSNumber\"), sel(\"numberWithBool:\"), (void *){decoration}L);"
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

    def apply(self, pid, wids):
        return self._run(pid, wids, apply=True)

    def restore(self, pid, wids):
        return self._run(pid, wids, apply=False)

    def _run(self, pid, wids, apply):
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
            val = thread.GetFrameAtIndex(0).EvaluateExpression(window_expr(wids, apply), opts)
            ok = val.IsValid() and val.GetError().Success()
            n = val.GetValueAsSigned() if ok else None
        finally:
            process.Detach()
            self.debugger.DeleteTarget(target)
        verb = "squared" if apply else "restored"
        if not ok:
            log(f"pid {pid}: expression failed: {val.GetError()}")
        elif n < 0:
            log(f"pid {pid}: not an AppKit app; corners left as is")
        elif n != len(wids):
            log(f"pid {pid}: {verb} {n} of {len(wids)} window(s)")
        return ok and n == len(wids)


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
        return self._tags(wids, "SLSSetWindowTags")

    def untag(self, wids):
        return self._tags(wids, "SLSClearWindowTags")

    def _tags(self, wids, function):
        self.process.Stop()
        if not self.wait_state(lldb.eStateStopped):
            log("interrupt timed out")
            return False
        frame = self.process.GetSelectedThread().GetSelectedFrame()
        val = frame.EvaluateExpression(tag_expr(wids, function))
        ok = val.IsValid() and val.GetError().Success()
        rc = val.GetValueAsSigned() if ok else None
        self.process.Continue()
        self.wait_state(lldb.eStateRunning)
        if not ok:
            log(f"expression failed: {val.GetError()}")
        elif rc != 0:
            log(f"{function} returned {rc} for {wids}")
        return ok and rc == 0

    def detach(self):
        if self.process and self.process.IsValid():
            self.process.Detach()
        self.process = None
        self.debugger.DeleteTarget(self.debugger.GetSelectedTarget())


def run(acts, dock, apps):
    if acts.untag and dock.process:
        log(f"untagging {' '.join(map(str, acts.untag))}")
        dock.untag(acts.untag)
    elif acts.untag:
        log(f"Dock not attached; could not untag {' '.join(map(str, acts.untag))}")
    for pid, wids in acts.restore.items():
        log(f"restoring pid {pid}: {' '.join(map(str, wids))}")
        apps.restore(pid, wids)
    for pid, wids in acts.apply.items():
        log(f"squaring pid {pid}: {' '.join(map(str, wids))}")
        apps.apply(pid, wids)
    if acts.tag and dock.process:
        log(f"tagging {' '.join(map(str, acts.tag))}")
        dock.tag(acts.tag)
    elif acts.tag:
        log(f"Dock not attached; could not tag {' '.join(map(str, acts.tag))}")


def main():
    global lldb
    only = None
    if "--pids" in sys.argv:
        only = {int(p) for p in sys.argv[sys.argv.index("--pids") + 1].split(",")}
    if sip_blocks_debugging():
        status("SIP enabled")
        return 1
    lldb = load_lldb()
    if lldb is None:
        status("Xcode missing")
        return 1

    dock = Dock()
    apps = Apps()
    tracker = windowstate.Tracker()
    parent = os.getppid()
    stop = {"flag": False}

    def on_signal(signum, _frame):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    reported = None
    attach_failed = False
    try:
        while not stop["flag"]:
            if dock.process is None and not dock.attach():
                if os.getppid() != parent:
                    log("parent process exited; stopping")
                    break
                if not attach_failed:
                    status("Dock attach failed")
                    attach_failed = True
                    reported = None
                time.sleep(2)
                continue
            attach_failed = False
            scanner = subprocess.Popen([WINSCAN, "--watch"], stdout=subprocess.PIPE, bufsize=0)
            fd = scanner.stdout.fileno()
            partial = b""
            try:
                while not stop["flag"]:
                    # winscan writes a line every 250 ms and an action takes up to ~1 s, so lines
                    # queue up. Act only on the newest one; older ones show stale window states.
                    readable = select.select([fd], [], [], 1.0)[0]
                    if os.getppid() != parent:
                        log("parent process exited; stopping")
                        stop["flag"] = True
                        break
                    if not readable:
                        continue
                    data = os.read(fd, 1 << 20)  # more than a pipe holds: everything available
                    if not data:  # EOF: winscan exited (a partial last line is dropped)
                        log("winscan exited; restarting")
                        break
                    line, partial = windowstate.latest_line(partial + data)
                    if line is None:
                        continue
                    if not dock.alive():
                        break
                    windows = windowstate.parse_watch(line)
                    if only is not None:
                        windows = [w for w in windows if w.pid in only]
                    skip = {os.getpid(), parent, dock.process.GetProcessID()}
                    run(tracker.update(windows, time.time(), skip), dock, apps)
                    count = sum(1 for w in windows if w.wid in tracker.applied)
                    if count != reported:
                        reported = count
                        status(f"running, {reported} windows")
            finally:
                scanner.kill()
                scanner.wait()
    finally:
        acts = tracker.restore_all()
        acts.restore = {pid: wids for pid, wids in acts.restore.items() if pid_alive(pid)}
        if not acts.empty():
            if dock.process is None:
                dock.attach()
            run(acts, dock, apps)
        if dock.process is not None:
            dock.detach()
        log("exiting")
        status("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
