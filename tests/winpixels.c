// winpixels: read a window capture (screencapture -x -o -l <wid> out.png) and print
// "square=<0|1> rim=<0|1>". square: all four corner pixels opaque. rim: the top row at the
// middle is clearly lighter than the titlebar 6 px below it (AppKit's titlebar highlight).
#include <CoreGraphics/CoreGraphics.h>
#include <ImageIO/ImageIO.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: winpixels <png>\n");
        return 2;
    }
    CFURLRef url = CFURLCreateFromFileSystemRepresentation(NULL, (const UInt8 *)argv[1], strlen(argv[1]), false);
    CGImageSourceRef src = CGImageSourceCreateWithURL(url, NULL);
    CGImageRef img = src ? CGImageSourceCreateImageAtIndex(src, 0, NULL) : NULL;
    if (!img) {
        fprintf(stderr, "winpixels: cannot read %s\n", argv[1]);
        return 1;
    }
    size_t w = CGImageGetWidth(img), h = CGImageGetHeight(img);
    uint8_t *buf = calloc(w * h, 4);
    CGColorSpaceRef rgb = CGColorSpaceCreateDeviceRGB();
    CGContextRef ctx = CGBitmapContextCreate(buf, w, h, 8, w * 4, rgb, kCGImageAlphaPremultipliedLast);
    CGContextDrawImage(ctx, CGRectMake(0, 0, w, h), img);
#define PX(x, y) (buf + ((size_t)(y) * w + (size_t)(x)) * 4)
    int square = PX(0, 0)[3] == 255 && PX(w - 1, 0)[3] == 255 && PX(0, h - 1)[3] == 255 && PX(w - 1, h - 1)[3] == 255;
    uint8_t *top = PX(w / 2, 0), *below = PX(w / 2, 6);
    int rim = top[0] + top[1] + top[2] > below[0] + below[1] + below[2] + 24;
    printf("square=%d rim=%d\n", square, rim);
    CGContextRelease(ctx);
    CGColorSpaceRelease(rgb);
    CGImageRelease(img);
    CFRelease(src);
    CFRelease(url);
    free(buf);
    return 0;
}
