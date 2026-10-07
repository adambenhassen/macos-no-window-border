LABEL = local.macos-no-window-border
PLIST = $(HOME)/Library/LaunchAgents/$(LABEL).plist
UID  := $(shell id -u)

all: winscan

winscan: winscan.c
	clang -O2 -Wall -o $@ $< -framework CoreFoundation -framework CoreGraphics \
		-F/System/Library/PrivateFrameworks -framework SkyLight

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

.PHONY: all install uninstall status clean
