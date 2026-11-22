#!/bin/bash
# PreToolUse hook on Bash. When Claude is about to merge into main or push main, run the
# test suite in the folder it is working in. Failing tests block the command (exit 2).
PY=/Users/sam/cycling-coach/venv/bin/python
input=$(cat)
field() { printf '%s' "$input" | "$PY" -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_input', {}).get('command', '') if sys.argv[1] == 'command' else d.get('cwd') or '.')" "$1"; }
cmd=$(field command)
case "$cmd" in *"git merge"*|*"git push"*) ;; *) exit 0 ;; esac
cwd=$(field cwd)
branch=$(git -C "$cwd" branch --show-current 2>/dev/null)
if [ "$branch" != main ] && ! printf '%s' "$cmd" | grep -qw main; then exit 0; fi
cd "$cwd" || exit 0
out=$("$PY" -m pytest tests -q 2>&1)
if [ $? -ne 0 ]; then
  echo "Blocked: the tests fail, so this will not merge into or push main. Fix them first." >&2
  printf '%s\n' "$out" | grep -E "^(FAILED|ERROR) |^[0-9]+ (passed|failed|error)" | tail -20 >&2
  exit 2
fi
exit 0
