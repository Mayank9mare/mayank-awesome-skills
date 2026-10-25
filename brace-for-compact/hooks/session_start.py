#!/usr/bin/env python3
"""SessionStart hook: put .claude/brace-state.md back into context after a compaction, /clear or
resume. On a fresh startup, only mention that an open state file exists. Never fails the session."""
import json
import os
import sys
import time

MAX_CHARS = 12000


def age(seconds):
    m = int(seconds // 60)
    if m < 1:
        return "just now"
    if m < 60:
        return f"{m} min ago"
    h = m // 60
    return f"{h} h ago" if h < 48 else f"{h // 24} days ago"


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    source = data.get("source", "")
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    path = os.path.join(root, ".claude", "brace-state.md")
    if not os.path.isfile(path):
        return
    text = open(path, encoding="utf-8", errors="replace").read()
    first = text.splitlines()[0] if text.strip() else ""
    if "CLOSED" in first.upper():
        return
    when = age(time.time() - os.path.getmtime(path))
    if source == "startup":
        print(f"[brace-for-compact] An open session state file exists at .claude/brace-state.md "
              f"(saved {when}): \"{first[:160]}\". Ask the user whether to resume it "
              f"(/brace-for-compact resume) before starting something new.")
        return
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n… (truncated; read the full file)"
    print(f"[brace-for-compact] Session state from .claude/brace-state.md, saved {when}, restored after "
          f"{source or 'session start'}. Resume from it: verify it against git and the files it names, "
          f"tell the user in a few lines where things stand, then continue.\n\n{text}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
