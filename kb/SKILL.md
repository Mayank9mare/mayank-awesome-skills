---
name: kb
description: Work knowledgebase for team context, people, projects, and Slack reply drafting. Use /kb to browse, /kb add to save, /kb search to find.
user-invocable: true
---

# Work Knowledgebase

Manages a persistent knowledgebase at `~/.claude/knowledgebase/` for work context.

## Usage

Parse the user's input after `/kb`:

### `/kb` (no args)
Read and display `~/.claude/knowledgebase/INDEX.md` to show what's in the knowledgebase.

### `/kb add <category> <topic>`
Categories: `person`, `project`, `process`, `incident`, `context`

1. Ask the user what they want to record (or extract from conversation context)
2. Write a markdown file to the appropriate subdirectory:
   - person → `~/.claude/knowledgebase/people/<topic>.md`
   - project → `~/.claude/knowledgebase/projects/<topic>.md`
   - process → `~/.claude/knowledgebase/processes/<topic>.md`
   - incident → `~/.claude/knowledgebase/incidents/<topic>.md`
   - context → `~/.claude/knowledgebase/context/<topic>.md`
3. Update `~/.claude/knowledgebase/INDEX.md` with a link to the new entry

### `/kb search <query>`
1. Use Grep to search across all files in `~/.claude/knowledgebase/` for the query
2. Read matching files and present a summary of relevant knowledge

### `/kb learn`
Extract knowledge from recent Slack conversations:
1. Use slack_search_public_and_private to find recent messages in team channels
2. Identify new people, projects, decisions, or context worth saving
3. Present findings and ask which to save

## When drafting Slack replies
Before drafting any Slack reply on behalf of the user:
1. Read `~/.claude/knowledgebase/context/communication-style.md`
2. Read `~/.claude/knowledgebase/people/team.md` to understand the relationship
3. Search the knowledgebase for any relevant project/context
4. Draft the reply matching the user's tone and style
