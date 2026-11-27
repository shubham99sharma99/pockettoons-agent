#!/usr/bin/env bash
# Commit and push eval progress (eval/results*, incl. the partial.json checkpoints) every
# INTERVAL seconds while the process PID runs, and once more after it exits.
#   scripts/autosave.sh <pid> [interval_s]
set -u
PID=$1; INTERVAL=${2:-120}
cd "$(dirname "$0")/.."
save() {
  [ -z "$(git status --porcelain -- eval/results eval/results.md)" ] && return 0
  n=$(python3 -c "import json;print(len(json.load(open('eval/results/partial.json'))))" 2>/dev/null || echo "?")
  git add -A -- eval/results eval/results.md
  git commit -q -m "eval progress: $n question(s) checkpointed ($1)" || return 0
  for d in 2 4 8 16; do git push -q origin HEAD && return 0; sleep $d; done
  echo "autosave: push failed; will retry next interval" >&2
}
while kill -0 "$PID" 2>/dev/null; do sleep "$INTERVAL"; save "autosave"; done
save "final"
