#!/bin/zsh
# Regression check: noborder only runs its AppKit expression in an app whose main thread is idle.
# Attaches only to a tests/hostapp it starts, never to Dock, so it can run next to NoBorder.app.
# It works on the floating window and un-maximizes "max" at once, so a running NoBorder leaves
# the test app alone.
set -u
typeset -F SECONDS  # fractional, so the poll timeout is exact
cd "${0:A:h}/.."
out=build/idle
mkdir -p $out
fail=0

host=""
cleanup() { [[ -n $host ]] && kill $host 2>/dev/null }
trap cleanup EXIT
trap 'exit 130' INT TERM

apply() {  # apply <pid> <wid>: prints what Apps.apply returns
    "$(xcode-select -p)/usr/bin/python3" -c 'import sys
sys.path.insert(0, ".")
import noborder
noborder.lldb = noborder.load_lldb()
print(noborder.Apps().apply(int(sys.argv[1]), [int(sys.argv[2])]))' $1 $2 | tail -n 1
}

pixels() {  # pixels <wid>: winpixels output for the window's current capture
    screencapture -x -o -l $1 $out/w.png && tests/winpixels $out/w.png
}

expect() {  # expect <label> <got> <want>
    if [[ "$2" == "$3" ]]; then
        echo "PASS $1: $2"
    else
        echo "FAIL $1: got '$2', want '$3'"
        fail=1
    fi
}

tests/hostapp busy > $out/host.txt & host=$!
for _ in {1..40}; do win=$(awk '$1=="floating" {print $2}' $out/host.txt); [[ -n $win ]] && break; sleep 0.05; done
[[ -n $win ]] || { echo "FAIL hostapp printed no window"; exit 1 }
kill -USR1 $host  # before NoBorder's 0.5 s settle
sleep 1.5

expect "busy app: apply skipped" "$(apply $host $win)" "busy"
sleep 1
expect "busy app: corners untouched" "$(pixels $win)" "square=0 rim=1"

kill -HUP $host
sleep 0.5
expect "idle app: apply ran" "$(apply $host $win)" "ok"
deadline=$((SECONDS + 3))  # the corner call is queued on the run loop; give it time to draw
while px=$(pixels $win); [[ $px != square=1* ]] && (( SECONDS < deadline )); do sleep 0.25; done
expect "idle app: corners squared" "${px%% *}" "square=1"
exit $fail
