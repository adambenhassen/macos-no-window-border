#!/bin/zsh
# End-to-end check of noborder.py against tests/hostapp only. Needs SIP disabled and no other
# noborder daemon running (only one debugger can hold Dock).
set -u
cd "${0:A:h}/.."
out=build/e2e
mkdir -p $out
fail=0

probe() {  # probe <wid>: sets cols and px from the current screen state
    cols=$(./winscan --all | awk -F'\t' -v w=$1 '$1==w {print $(NF-1), $NF}')
    screencapture -x -o -l $1 $out/w.png
    px=$(tests/winpixels $out/w.png)
}

check() {  # check <label> <wid> <want winscan columns> <want winpixels output>; polls up to 15 s
    local cols px deadline=$((SECONDS + 15))
    while true; do
        probe $2
        [[ "$cols" == "$3" && "$px" == "$4" ]] && break
        (( SECONDS >= deadline )) && break
        sleep 0.5
    done
    if [[ "$cols" == "$3" && "$px" == "$4" ]]; then
        echo "PASS $1: $cols $px"
    else
        echo "FAIL $1: got '$cols' '$px', want '$3' '$4'"
        fail=1
    fi
}

host=""
daemon=""
cleanup() {
    [[ -n $daemon ]] && kill -0 $daemon 2>/dev/null && kill -TERM $daemon 2>/dev/null
    [[ -n $host ]] && kill $host 2>/dev/null
}
trap cleanup EXIT
trap 'exit 130' INT TERM

if pgrep -f 'noborder.py' >/dev/null; then
    echo "stop the running noborder daemon first"
    exit 2
fi
tests/hostapp > $out/host.txt & host=$!
sleep 1.5
max=$(awk '$1=="max" {print $2}' $out/host.txt)
float=$(awk '$1=="floating" {print $2}' $out/host.txt)

./noborder.py --pids $host > $out/daemon.log 2>&1 & daemon=$!
check "maximized applied" $max "[noshadow] [max]" "square=1 rim=0"
check "floating untouched" $float "[shadow] [nomax]" "square=0 rim=1"

kill -USR1 $host
check "un-maximized restored" $max "[shadow] [nomax]" "square=0 rim=1"
kill -USR2 $host
check "re-maximized applied" $max "[noshadow] [max]" "square=1 rim=0"

kill -TERM $daemon
for _ in {1..60}; do kill -0 $daemon 2>/dev/null || break; sleep 0.5; done
if kill -0 $daemon 2>/dev/null; then
    echo "FAIL daemon did not exit within 30 s; killing"
    kill -9 $daemon
    fail=1
fi
wait $daemon
code=$?
check "restored on SIGTERM" $max "[shadow] [max]" "square=0 rim=1"
if [[ $code == 0 ]] && grep -q '^status: stopped' $out/daemon.log; then
    echo "PASS clean exit with 'status: stopped'"
else
    echo "FAIL exit code $code or no 'status: stopped' line"
    fail=1
fi
exit $fail
