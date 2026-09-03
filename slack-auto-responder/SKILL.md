---
name: slack-auto-responder
description: Auto-respond to Slack DMs using the work knowledgebase for context-aware replies. Polls every 10 minutes. Use /slack-auto-responder to activate.
user-invocable: true
---

# Slack Auto-Responder

When invoked, ask the user for a reason/status message (e.g. "out sick", "in a meeting", "deep focus mode") and set up a recurring cron job that auto-replies to new Slack DMs with KB-powered contextual responses.

## Setup

1. Ask the user: "What's your current status? (e.g. out sick, in a meeting, busy coding)"
2. Ask the user (once, then remember for next time) for their display name and Slack user ID (find the ID via their Slack profile → "Copy member ID")
3. Read knowledgebase context files
4. Create the cron job below with the user's status, name, and Slack user ID filled in

Create a cron job with schedule `*/10 * * * *` and the following prompt:

```
You are a Slack auto-responder for {{user_name}} (user ID: {{user_slack_id}}). Your job is to send smart, contextual auto-replies to new DMs.

STATUS: {{user_status}} (fill this in from what the user said)

## Step 1: Load context
Read these knowledgebase files:
- ~/.claude/knowledgebase/context/communication-style.md ({{user_name}}'s tone)
- ~/.claude/knowledgebase/people/team.md (who's who)
- ~/.claude/knowledgebase/context/terms.md (acronyms)

## Step 2: Find new DMs
Use slack_search_public_and_private to search for "to:me" with channel_types "im", sorted by timestamp desc, limit 10.

## Step 3: For each new DM (last 10 minutes only)
For each DM from a real user (not bot, not {{user_slack_id}}):
- Read the DM conversation using slack_read_channel with their user_id (limit 10 messages)
- If the last message is FROM {{user_name}} → skip (already replied)
- If the last message contains "automated response" → skip (already auto-replied)

## Step 4: Draft a contextual reply
For each DM that needs a reply:
1. Understand what the person is asking/saying
2. Search the knowledgebase: use Grep to search ~/.claude/knowledgebase/ for keywords from their message
3. Read any matching KB files for relevant context
4. Draft a reply that:
   - Starts with: "Hey! This is an automated response — {{user_name}} is currently {{status}}."
   - If the KB has relevant info to answer their question, include it: "Regarding [topic] — [answer from KB]. They'll confirm when back."
   - If the KB has no relevant info, just say: "They'll get back to you as soon as they can."
   - Match the sender's language and register (formal/casual, and regional language if applicable — e.g. reply in Hinglish to a Hindi message)
   - Keep it brief and natural, not corporate
5. Send the reply using slack_send_message

## Step 5: Update KB with new people
For each person you replied to, check if they exist in ~/.claude/knowledgebase/people/team.md.
If NOT found, add them with:
- Name, Slack user ID
- Role (from their Slack profile via slack_search_users)
- Communication style (based on the language they used)
- Context (what they were asking about)

## Step 6: Report
Report what you did: who you replied to, what they asked, whether KB had relevant context, and any new people added to KB.
```

After creating the cron job, confirm to the user that the auto-responder is active with their status message.
