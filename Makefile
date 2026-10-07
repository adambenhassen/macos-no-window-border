APP = build/NoBorder.app

all: winscan app

winscan: winscan.m
	clang -O2 -Wall -fobjc-arc -o $@ $< -framework AppKit -framework CoreGraphics \
		-F/System/Library/PrivateFrameworks -framework SkyLight

app: winscan
	cd app && swift build -c release
	rm -rf $(APP)
	mkdir -p $(APP)/Contents/MacOS $(APP)/Contents/Resources
	cp app/Info.plist $(APP)/Contents/Info.plist
	cp app/.build/release/NoBorder $(APP)/Contents/MacOS/NoBorder
	cp noborder.py windowstate.py winscan $(APP)/Contents/Resources/
	codesign --force --sign - $(APP)

install: app
	rm -rf /Applications/NoBorder.app
	cp -R $(APP) /Applications/

test:
	python3 -m unittest discover -s tests -v
	cd app && swift test

testtools: tests/hostapp tests/winpixels

tests/hostapp: tests/hostapp.swift
	swiftc -O -o $@ $<

tests/winpixels: tests/winpixels.c
	clang -O2 -Wall -o $@ $< -framework CoreGraphics -framework ImageIO -framework CoreFoundation

clean:
	rm -rf winscan build app/.build tests/hostapp tests/winpixels

.PHONY: all app install test testtools clean
