#!/usr/bin/env python3
"""PreCompact hook: back up the transcript to .claude/brace-transcripts/ (keep the last 5), and if
.claude/brace-state.md is stale, tell the user. Never blocks compaction."""
import glob
import json
import os
import shutil
import sys
import time

KEEP = 5
STALE_MIN = 20


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    trigger = data.get("trigger", "") or "compact"
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    claude_dir = os.path.join(root, ".claude")

    transcript = data.get("transcript_path")
    if transcript and os.path.isfile(transcript):
        backups = os.path.join(claude_dir, "brace-transcripts")
        os.makedirs(backups, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        shutil.copyfile(transcript, os.path.join(backups, f"{stamp}-{trigger}.jsonl"))
        for old in sorted(glob.glob(os.path.join(backups, "*.jsonl")))[:-KEEP]:
            os.remove(old)

    state = os.path.join(claude_dir, "brace-state.md")
    if os.path.isfile(state):
        first = open(state, encoding="utf-8", errors="replace").readline()
        if "CLOSED" in first.upper():
            return
        minutes = (time.time() - os.path.getmtime(state)) / 60
        if minutes <= STALE_MIN:
            note = (f"An up-to-date session state file exists at .claude/brace-state.md "
                    f"(saved {int(minutes)} min ago); it will be restored after compaction.")
        else:
            note = (f"The session state file .claude/brace-state.md is {int(minutes)} min old and may be "
                    f"stale. Consider cancelling and running /brace-for-compact first.")
    else:
        return   # no state file in this project: nothing to say
    # PreCompact accepts no hookSpecificOutput (validation fails), so the note goes to the user only.
    print(json.dumps({"systemMessage": "[brace-for-compact] " + note}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
