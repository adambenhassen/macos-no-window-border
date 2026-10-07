// winscan: list on-screen, layer-0 (normal app) windows, their WindowServer shadow state, and
// whether each fills its screen's usable area (NSScreen.visibleFrame, within 2 pt).
//
//   winscan          print windows that still have a shadow:  <wid>\t<pid>\t<owner>\t<title>
//   winscan --all    print every normal window, plus [shadow]/[noshadow] and [max]/[nomax] columns
//   winscan --watch  every 250 ms print one line with a space-separated
//                    <wid>:<pid>:<shadow>:<maximized> token per normal window (empty line when
//                    none). Used by noborder.py.
//
// Shadow state is WindowServer tag bit 3 (what NSWindow.hasShadow toggles). Reading tags of
// foreign windows works from any process; setting them does not, hence noborder.py.
#import <AppKit/AppKit.h>
#include <CoreGraphics/CoreGraphics.h>
#include <math.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>

extern int SLSMainConnectionID(void);
extern int SLSGetWindowTags(int cid, uint32_t wid, uint64_t *tags, int maxTagSize);

#define NOSHADOW_BIT 3
#define MAX_TOLERANCE 2.0
#define MAX_SCREENS 16

static void cstr(CFStringRef s, char *buf, size_t n) {
    buf[0] = 0;
    if (s) CFStringGetCString(s, buf, n, kCFStringEncodingUTF8);
}

// Usable area of every screen in CG window coordinates (origin at the primary screen's top-left).
static int usable_rects(CGRect *out) {
    NSArray<NSScreen *> *screens = [NSScreen screens];
    if (screens.count == 0) return 0;
    CGFloat primary_h = screens[0].frame.size.height;
    int n = 0;
    for (NSScreen *s in screens) {
        if (n == MAX_SCREENS) break;
        NSRect v = s.visibleFrame;
        out[n++] = CGRectMake(v.origin.x, primary_h - v.origin.y - v.size.height, v.size.width, v.size.height);
    }
    return n;
}

static int is_maximized(CGRect b, const CGRect *usable, int n) {
    for (int i = 0; i < n; i++) {
        CGRect u = usable[i];
        if (fabs(b.origin.x - u.origin.x) <= MAX_TOLERANCE && fabs(b.origin.y - u.origin.y) <= MAX_TOLERANCE &&
            fabs(b.size.width - u.size.width) <= MAX_TOLERANCE && fabs(b.size.height - u.size.height) <= MAX_TOLERANCE)
            return 1;
    }
    return 0;
}

static int scan(int cid, int mode) {  // mode: 0 = shadowed, 1 = all, 2 = watch line
    CFArrayRef list = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements, kCGNullWindowID);
    if (!list) return 1;
    CGRect usable[MAX_SCREENS];
    int nusable = usable_rects(usable);
    int first = 1;
    for (CFIndex i = 0; i < CFArrayGetCount(list); i++) {
        CFDictionaryRef w = CFArrayGetValueAtIndex(list, i);
        int layer = -1, pid = 0;
        uint32_t wid = 0;
        CFNumberGetValue(CFDictionaryGetValue(w, kCGWindowLayer), kCFNumberIntType, &layer);
        CFNumberGetValue(CFDictionaryGetValue(w, kCGWindowNumber), kCFNumberSInt32Type, &wid);
        CFNumberGetValue(CFDictionaryGetValue(w, kCGWindowOwnerPID), kCFNumberIntType, &pid);
        if (layer != 0) continue;
        uint64_t tags[2] = {0, 0};
        if (SLSGetWindowTags(cid, wid, tags, 64) != 0) continue;
        int noshadow = (tags[0] >> NOSHADOW_BIT) & 1;
        CGRect bounds = CGRectZero;
        CGRectMakeWithDictionaryRepresentation(CFDictionaryGetValue(w, kCGWindowBounds), &bounds);
        int maximized = is_maximized(bounds, usable, nusable);
        if (mode == 2) {
            printf(first ? "%u:%d:%d:%d" : " %u:%d:%d:%d", wid, pid, !noshadow, maximized);
            first = 0;
            continue;
        }
        if (noshadow && mode != 1) continue;
        char owner[256], title[512];
        cstr(CFDictionaryGetValue(w, kCGWindowOwnerName), owner, sizeof owner);
        cstr(CFDictionaryGetValue(w, kCGWindowName), title, sizeof title);
        if (mode == 1)
            printf("%u\t%d\t%s\t%s\t%s\t%s\n", wid, pid, owner, title, noshadow ? "[noshadow]" : "[shadow]", maximized ? "[max]" : "[nomax]");
        else
            printf("%u\t%d\t%s\t%s\n", wid, pid, owner, title);
    }
    CFRelease(list);
    if (mode == 2) {
        printf("\n");
        fflush(stdout);
    }
    return 0;
}

int main(int argc, char **argv) {
    @autoreleasepool {
        // NSScreen updates its geometry from screen-change notifications, which need an
        // NSApplication and a running run loop. Prohibited policy: no Dock icon, no menu bar.
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
        int cid = SLSMainConnectionID();
        if (argc > 1 && strcmp(argv[1], "--watch") == 0) {
            for (;;) {
                @autoreleasepool {
                    if (scan(cid, 2) != 0) return 1;
                    [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.25]];
                }
            }
        }
        return scan(cid, argc > 1 && strcmp(argv[1], "--all") == 0 ? 1 : 0);
    }
}
