// winscan: list on-screen, layer-0 (normal app) windows and their WindowServer shadow state.
//
//   winscan          print windows that still have a shadow:  <wid>\t<pid>\t<owner>\t<title>
//   winscan --all    print every normal window, with a trailing [shadow] / [noshadow] column
//   winscan --watch  every 250 ms print one line with the space-separated wids that still
//                    have a shadow (empty line when none). Used by noborder.py.
//
// Shadow state is WindowServer tag bit 3 (what NSWindow.hasShadow toggles). Reading tags of
// foreign windows works from any process; setting them does not, hence noborder.py.
#include <CoreFoundation/CoreFoundation.h>
#include <CoreGraphics/CoreGraphics.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>

extern int SLSMainConnectionID(void);
extern int SLSGetWindowTags(int cid, uint32_t wid, uint64_t *tags, int maxTagSize);

#define NOSHADOW_BIT 3

static void cstr(CFStringRef s, char *buf, size_t n) {
    buf[0] = 0;
    if (s) CFStringGetCString(s, buf, n, kCFStringEncodingUTF8);
}

static int scan(int cid, int mode) {  // mode: 0 = shadowed, 1 = all, 2 = watch line
    CFArrayRef list = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements, kCGNullWindowID);
    if (!list) return 1;
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
        if (noshadow && mode != 1) continue;
        if (mode == 2) {
            printf(first ? "%u" : " %u", wid);
            first = 0;
            continue;
        }
        char owner[256], title[512];
        cstr(CFDictionaryGetValue(w, kCGWindowOwnerName), owner, sizeof owner);
        cstr(CFDictionaryGetValue(w, kCGWindowName), title, sizeof title);
        printf("%u\t%d\t%s\t%s%s\n", wid, pid, owner, title, mode == 1 ? (noshadow ? "\t[noshadow]" : "\t[shadow]") : "");
    }
    CFRelease(list);
    if (mode == 2) {
        printf("\n");
        fflush(stdout);
    }
    return 0;
}

int main(int argc, char **argv) {
    int cid = SLSMainConnectionID();
    if (argc > 1 && strcmp(argv[1], "--watch") == 0) {
        for (;;) {
            if (scan(cid, 2) != 0) return 1;
            usleep(250 * 1000);
        }
    }
    return scan(cid, argc > 1 && strcmp(argv[1], "--all") == 0 ? 1 : 0);
}
