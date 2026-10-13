#!/usr/bin/env bash
# Model-check every config in models/ and compare TLC's outcome with the
# "Expected:" line at the top of the config.
#
#   ./check.sh                  all models
#   ./check.sh proposed         one model, by exact name
#   ./check.sh proposed_mutant  a group, by name prefix
#
# Every run is capped, so a model larger than expected cannot take the machine
# down. Override with:
#   TLC_MEMORY   memory for TLC and its files, as a systemd user scope (8G)
#   TLC_HEAP     JVM heap (4g)
#   TLC_WORKERS  worker threads (all cores but 4)
#   TLC_TIMEOUT  wall-clock limit per model, as for timeout(1) (15m)
#   TLA2TOOLS    path to tla2tools.jar
# TLC's state queue and fingerprint files go to out/states/, on disk: /tmp may
# be a tmpfs, where files take RAM. Checkpoints are off.
set -u
cd "$(dirname "$0")"

jar="${TLA2TOOLS:-/opt/TLA+Toolbox/tla2tools.jar}"
cores="$(nproc)"
workers="${TLC_WORKERS:-$((cores > 5 ? cores - 4 : 1))}"
mkdir -p out/states
failures=0

limit=()
if systemd-run --user --scope --quiet true 2> /dev/null; then
    limit=(systemd-run --user --scope --quiet
           -p MemoryMax="${TLC_MEMORY:-8G}" -p MemorySwapMax=0)
else
    echo "warning: no systemd user scope; only the JVM heap is capped" >&2
fi

if [ -n "${1:-}" ] && [ -f "models/$1.cfg" ]; then
    cfgs=("models/$1.cfg")
else
    cfgs=(models/"${1:-}"*.cfg)
fi

for cfg in "${cfgs[@]}"; do
    name="$(basename "$cfg" .cfg)"
    case "$name" in
        current_*) spec=EtagCurrent.tla ;;
        proposed | proposed_*) spec=EtagProposed.tla ;;
        token | token_*) spec=EtagToken.tla ;;
        *) echo "skip $name: unknown spec"; continue ;;
    esac
    expected="$(sed -n 's/^\\\* Expected: \(.*\)\.$/\1/p' "$cfg")"
    meta="out/states/$name"
    rm -rf "$meta"
    mkdir -p "$meta"
    "${limit[@]}" timeout "${TLC_TIMEOUT:-15m}" nice -n 19 \
        java -Xmx"${TLC_HEAP:-4g}" -XX:+UseParallelGC -cp "$jar" tlc2.TLC \
            -workers "$workers" -deadlock -checkpoint 0 \
            -metadir "$meta" -config "$cfg" "$spec" > "out/$name.log" 2>&1
    status=$?
    rm -rf "$meta"

    if [ "$status" -eq 124 ]; then
        actual="timed out"
    elif [ "$status" -eq 137 ]; then
        actual="out of memory"
    elif grep -q "No error has been found" "out/$name.log"; then
        actual="no error"
    elif inv="$(sed -n 's/^Error: Invariant \(.*\) is violated\.$/\1/p' "out/$name.log")" && [ -n "$inv" ]; then
        actual="$inv violated"
    else
        actual="TLC error"
    fi
    states="$(sed -n 's/.* \([0-9,]*\) distinct states found.*/\1/p' "out/$name.log" | tail -1)"

    if [ "$actual" = "$expected" ]; then verdict=ok; else verdict=UNEXPECTED; failures=$((failures + 1)); fi
    printf '%-34s %-10s %-30s %12s states\n' "$name" "$verdict" "$actual" "${states:-?}"
done

exit "$failures"
