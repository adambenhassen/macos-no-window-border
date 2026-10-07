LABEL = local.macos-no-window-border
PLIST = $(HOME)/Library/LaunchAgents/$(LABEL).plist
UID  := $(shell id -u)

all: winscan

winscan: winscan.m
	clang -O2 -Wall -fobjc-arc -o $@ $< -framework AppKit -framework CoreGraphics \
		-F/System/Library/PrivateFrameworks -framework SkyLight

testtools: tests/hostapp tests/winpixels

tests/hostapp: tests/hostapp.swift
	swiftc -O -o $@ $<

tests/winpixels: tests/winpixels.c
	clang -O2 -Wall -o $@ $< -framework CoreGraphics -framework ImageIO -framework CoreFoundation

install: winscan
	mkdir -p $(HOME)/Library/LaunchAgents $(HOME)/Library/Logs
	sed -e 's|@ROOT@|$(CURDIR)|g' -e 's|@HOME@|$(HOME)|g' launchagent.plist > $(PLIST)
	-launchctl bootout gui/$(UID)/$(LABEL) 2>/dev/null
	launchctl bootstrap gui/$(UID) $(PLIST)

uninstall:
	-launchctl bootout gui/$(UID)/$(LABEL) 2>/dev/null
	rm -f $(PLIST)

status:
	-launchctl print gui/$(UID)/$(LABEL) | grep -E '^\s*(state|pid) '
	tail -n 5 $(HOME)/Library/Logs/macos-no-window-border.log

clean:
	rm -f winscan

.PHONY: all install uninstall status clean testtools
