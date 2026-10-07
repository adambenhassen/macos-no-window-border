#!/bin/zsh
# End-to-end check of noborder.py against tests/hostapp only. Needs SIP disabled and no other
# noborder daemon running (only one debugger can hold Dock).
set -u
typeset -F SECONDS  # fractional, so short check timeouts are exact
cd "${0:A:h}/.."
out=build/e2e
mkdir -p $out
fail=0

probe() {  # probe <wid>: sets cols and px from the current screen state
    cols=$(./winscan --all | awk -F'\t' -v w=$1 '$1==w {print $(NF-1), $NF}')
    screencapture -x -o -l $1 $out/w.png
    px=$(tests/winpixels $out/w.png)
}

check() {  # check <label> <wid> <want winscan columns> <want winpixels output> [timeout s, default 15]
    local cols px deadline=$((SECONDS + ${5:-15}))
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

tagcount() {  # tagcount <log> <wid>: number of "tagging" log lines that name <wid>
    awk -v w=$2 '$3=="tagging" { for (i = 4; i <= NF; i++) if ($i == w) { n++; break } } END { print n + 0 }' $1
}

host=""
daemon=""
parent=""
daemon2=""
cleanup() {
    [[ -n $parent ]] && kill -9 $parent 2>/dev/null
    for d in $daemon $daemon2; do  # SIGTERM restores; wait up to 30 s before killing the host
        kill -TERM $d 2>/dev/null || continue
        for _ in {1..60}; do kill -0 $d 2>/dev/null || break; sleep 0.5; done
        kill -9 $d 2>/dev/null
    done
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
before=$(tagcount $out/daemon.log $max)
sleep 6
after=$(tagcount $out/daemon.log $max)
if (( after == before )); then
    echo "PASS no re-tagging of an applied window: $after tagging lines"
else
    echo "FAIL applied window re-tagged: $before -> $after tagging lines in 6 s"
    fail=1
fi
check "floating untouched" $float "[shadow] [nomax]" "square=0 rim=1"

kill -USR1 $host
check "un-maximized restored" $max "[shadow] [nomax]" "square=0 rim=1"
kill -USR2 $host
check "re-maximized applied (warm, within 3 s)" $max "[noshadow] [max]" "square=1 rim=0" 3

kill -TERM $daemon
for _ in {1..60}; do kill -0 $daemon 2>/dev/null || break; sleep 0.5; done
if kill -0 $daemon 2>/dev/null; then
    echo "FAIL daemon did not exit within 30 s; killing"
    kill -9 $daemon
    fail=1
fi
wait $daemon
code=$?
daemon=""  # reaped; never signal its pid again
check "restored on SIGTERM" $max "[shadow] [max]" "square=0 rim=1"
if [[ $code == 0 ]] && grep -q '^status: stopped' $out/daemon.log; then
    echo "PASS clean exit with 'status: stopped'"
else
    echo "FAIL exit code $code or no 'status: stopped' line"
    fail=1
fi

# The app reads the daemon's output through a pipe. When the app dies, the daemon must still
# restore every window although the pipe has no reader.
python3 -c 'import subprocess, sys
p = subprocess.Popen(sys.argv[1:], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
print(p.pid, flush=True)
for line in p.stdout:
    sys.stdout.buffer.write(line)
    sys.stdout.flush()' ./noborder.py --pids $host > $out/parent.log & parent=$!
for _ in {1..20}; do daemon2=$(head -n 1 $out/parent.log); [[ -n $daemon2 ]] && break; sleep 0.25; done
check "maximized applied under a piped parent" $max "[noshadow] [max]" "square=1 rim=0"
kill -9 $parent
wait $parent 2>/dev/null
killed=$SECONDS
while kill -0 $daemon2 2>/dev/null && (( SECONDS < killed + 15 )); do sleep 0.25; done
if kill -0 $daemon2 2>/dev/null; then
    echo "FAIL daemon did not exit within 15 s of its parent's death"
    fail=1
else
    daemon2=""
    printf "PASS daemon exited %.1f s after its parent's death\n" $((SECONDS - killed))
fi
left=$((killed + 15 - SECONDS))
check "restored after parent death" $max "[shadow] [max]" "square=0 rim=1" $(( left > 1 ? left : 1 ))
exit $fail
