---
name: memory-expert
description: Execute memory tools first, then personalize responses using past context. Blocking requirement at conversation start.
---

# Memory Expert Skill (v2.0)

## 🛑 BLOCKING REQUIREMENT: Execute This Tool Call NOW

**Before reading anything else or responding to the user, execute this tool call:**

```
mcp__memory__search_memory(
    query="user preferences work context recent solutions",
    limit=10
)
```

**ONLY exception**: User's message explicitly contains "don't check memory" OR "skip memory"

---

## ✓ CHECKPOINT: Did You Execute the Tool Call?

**Check one:**

- [ ] ✅ YES - I called `mcp__memory__search_memory` → Proceed to "How to Use Results" section
- [ ] ❌ NO - STOP. Go back and execute the tool call above. Do not continue.
- [ ] ⚠️ EXCEPTION - User said "don't check memory" or "skip memory" → Skip memory this session

---

## How to Use Memory Search Results

**You'll receive a response like this:**

```json
{
  "results": [
    {
      "memory": "[PREFERENCE] Prefers Mermaid diagrams over ASCII art",
      "metadata": {
        "user_id": "alice@example.com",
        "memory_type": "preference",
        "confidence": 0.95
      },
      "score": 0.87
    },
    {
      "memory": "[CONTEXT] Owns payment-service and settlement-service",
      "metadata": {
        "user_id": "alice@example.com",
        "memory_type": "context",
        "confidence": 0.90
      },
      "score": 0.82
    },
    {
      "memory": "[SOLUTION] payment-service timeout from Redis pool exhaustion. Fixed by increasing max_connections to 50.",
      "metadata": {
        "user_id": "alice@example.com",
        "memory_type": "solution",
        "confidence": 0.85
      },
      "score": 0.76
    }
  ]
}
```

### Apply These Learnings:

**1. Filter results**
- Ignore memories with `score < 0.5` (low relevance)
- Validate `metadata.user_id` matches current user (prevent contamination)

**2. Look for prefix tags and adapt:**

| Prefix | What to Do |
|--------|-----------|
| `[PREFERENCE]` | **Adapt your communication style**<br>Example: "Prefers Mermaid" → Use Mermaid diagrams, not ASCII |
| `[CONTEXT]` | **Prioritize relevant services**<br>Example: "Owns payment-service" → Check payment-service first in investigations |
| `[SOLUTION]` | **Reference past solutions**<br>Example: "Redis timeout fixed by pool increase" → Check if current issue matches pattern |
| `[DECISION]` | **Respect past architectural choices**<br>Example: "Chose PostgreSQL for ACID" → Don't suggest MongoDB |
| `[PATTERN]` | **Follow user's workflow**<br>Example: "Debugs: logs → DB → cache" → Use that investigation order |

**3. Proactively mention relevant memories:**
- "Based on our previous work, you own payment-service - I'll check that first"
- "Last time we fixed this by increasing Redis pool connections - checking if it's the same issue"
- "I'll use Mermaid diagrams as you prefer"

---

## When to Store Memory

**After completing the user's request, ask these 3 questions:**

### Question 1: Do I have user_id?
```
Get user_id from conversation context OR call a user/persona lookup tool if one is available
```
- ❌ **NO** → DO NOT STORE (CRITICAL: prevents contamination)
- ✅ **YES** → Continue to Question 2

### Question 2: Is this worth remembering?

**Store ONLY if it matches at least ONE of these:**

✅ **Explicit preference** - User directly stated: "I prefer X", "I always use Y", "Show me Z format"

✅ **Complex solution** - Investigation used 5+ tool calls AND resolved a non-obvious issue

✅ **Ownership claim** - User said "I own X service" (verify with `graph_query` first)

✅ **Recurring issue** - This is the 3rd+ time user hit this same problem

❌ **None of above** → DO NOT STORE

✅ **Matches criteria** → Continue to Question 3

### Question 3: What's my confidence level?

| Confidence | When to Use |
|-----------|-------------|
| **0.9-1.0** | User explicitly stated with no ambiguity |
| **0.7-0.9** | Strong evidence (2-3 observations or verified fact) |
| **0.5-0.7** | Moderate evidence (1 observation, reasonable inference) |
| **<0.5** | ❌ DO NOT STORE - too uncertain |

✅ **Confidence ≥ 0.5** → STORE IT (see "How to Store" below)

---

## How to Store Memory

**Tool call syntax:**

```
mcp__memory__add_memory(
    messages=[
        {
            "role": "user",
            "content": "Short user statement or fact"
        },
        {
            "role": "assistant",
            "content": "Brief acknowledgment response"
        }
    ],
    metadata={
        "user_id": "alice@example.com",        // REQUIRED (get from context)
        "memory_type": "preference|solution|context|decision|pattern",
        "confidence": 0.85,                   // Use table above
        "created_at": "2026-01-22T09:30:00Z", // ISO 8601 timestamp
        "category": "communication.visualization",  // Optional but helpful
        "services": ["payment-service"]       // Optional, for solutions
    }
)
```

**⚠️ CRITICAL: Messages MUST be conversational pairs (user + assistant)**

The memory service expects a natural conversation exchange, NOT single statements with prefix tags.

### ⚠️ CRITICAL: Message Length Constraints

**The memory service has strict length limits. Messages MUST be:**

- **Short and conversational** (10-15 words maximum)
- **Simple sentence structure** (no complex formatting, bullets, or nested data)
- **No special characters or JSON-like structures** in content
- **Natural language only** (like a casual conversation exchange)

**❌ WRONG - Will fail silently:**
```json
{
  "messages": [{
    "role": "user",
    "content": "Investigated payment-service timeout issue using Loki logs and DataDog metrics. Found Redis connection pool exhaustion with max_connections at 10. Applied fix by increasing pool size to 50 in application.yml and redeploying via Jenkins pipeline job #1234 which completed successfully after 15 minutes."
  }]
}
```

**✅ CORRECT - Will work:**
```json
{
  "messages": [
    {
      "role": "user",
      "content": "Fixed payment-service timeout by increasing Redis pool to 50"
    },
    {
      "role": "assistant",
      "content": "Great solution. Recorded for future reference."
    }
  ]
}
```

**Best practices:**
- Keep total message under 15 words
- Use simple declarative sentences
- Remove unnecessary details (keep only core insight)
- No formatting (no bullets, code blocks, or structured data)

### Working Examples (Copy-Paste Ready)

**⚠️ IMPORTANT: Use conversational pairs (user + assistant) - NOT single messages**

**Example 1: Preference**
```json
{
  "messages": [
    {
      "role": "user",
      "content": "I prefer Mermaid diagrams over ASCII"
    },
    {
      "role": "assistant",
      "content": "Noted. I'll use Mermaid diagrams for visualizations."
    }
  ],
  "metadata": {
    "user_id": "alice@example.com",
    "memory_type": "preference",
    "confidence": 0.95
  }
}
```

**Example 2: Solution**
```json
{
  "messages": [
    {
      "role": "user",
      "content": "Fixed payment-service timeout by increasing Redis pool to 50"
    },
    {
      "role": "assistant",
      "content": "Great fix. Stored solution for future reference."
    }
  ],
  "metadata": {
    "user_id": "alice@example.com",
    "memory_type": "solution",
    "confidence": 0.85,
    "services": ["payment-service"]
  }
}
```

**Example 3: Context**
```json
{
  "messages": [
    {
      "role": "user",
      "content": "I work on Payments pod and own payment-service"
    },
    {
      "role": "assistant",
      "content": "Noted. Recorded your ownership of payment-service."
    }
  ],
  "metadata": {
    "user_id": "alice@example.com",
    "memory_type": "context",
    "confidence": 0.90
  }
}
```

### Memory Types Guide:

| Type | Use For | Example Conversation |
|------|---------|---------------------|
| `preference` | User's communication/tool preferences | User: "I prefer concise responses"<br>Assistant: "Noted. I'll keep responses brief." |
| `solution` | Solved technical problems | User: "Fixed timeout by increasing Redis pool to 50"<br>Assistant: "Great fix. Stored solution." |
| `context` | User's work context | User: "I work on Payments pod and own payment-service"<br>Assistant: "Noted your ownership." |
| `decision` | Architectural choices | User: "We chose PostgreSQL over MongoDB for ACID"<br>Assistant: "Recorded architectural decision." |
| `pattern` | User's recurring workflow | User: "I debug by checking logs then DB then cache"<br>Assistant: "Noted your debugging workflow." |

---

## ❌ DO NOT Store These

**Critical anti-patterns:**

1. **Missing user_id** - Causes cross-user contamination (CRITICAL BUG)
2. **Sensitive data** - Passwords, API keys, employee IDs, PII, credentials
3. **Trivial info** - Greetings ("Hello"), generic statements ("I'm an engineer"), one-off requests
4. **Knowledge graph data** - Service ownership/dependencies already in graph (use graph_query instead)
5. **Unsolved issues** - Only store solutions, not investigations in progress
6. **Too many memories** - Max 2-3 per conversation (if you're storing 5+, you're over-storing)

---

## Quick Reference Card

### Every Conversation:
```
1. Call mcp__memory__search_memory (REQUIRED)
2. Apply learnings to your response
3. After solving: Store if worth remembering (3-question test)
```

### Memory Search Query Patterns:
- General: `"user preferences work context recent solutions"`
- Specific service: `"payment-service timeout solutions"`
- Communication: `"preference response format diagrams"`

### Minimal Metadata (Required Fields Only):
```json
{
  "user_id": "user@example.com",    // REQUIRED
  "memory_type": "preference",     // REQUIRED
  "confidence": 0.85              // REQUIRED
}
```

---

## Success Checklist (Self-Validation)

**After completing a user request, verify:**

- [ ] ✅ I called `mcp__memory__search_memory` at the start (or user said skip)
- [ ] ✅ I applied relevant learnings to my response
- [ ] ✅ I mentioned relevant past context proactively
- [ ] ✅ If I stored memory: used 3-question test + included user_id
- [ ] ✅ I did not store: sensitive data, trivial info, or knowledge graph duplicates

**Red flags (indicates error):**
- 🚩 I stored memory without user_id
- 🚩 I stored 4+ memories in one conversation
- 🚩 I didn't check memory but user asked "what do you remember?"
- 🚩 I asked "which service?" when user mentioned it earlier in conversation

---

## Advanced Topics (Appendix)

### Optional Metadata Fields

Add these for richer context (but not required):

```json
{
  "category": "communication.visualization",   // Standardized categories
  "services": ["payment-service"],             // Relevant services
  "occurrence_count": 3,                       // For recurring issues
  "pattern_detected": true,                    // Flag recurring patterns
  "evidence_count": 2,                         // Number of observations
  "supersedes": "mem_abc123"                   // Replaces old memory
}
```

### Standard Categories

**Preference:** `communication.format`, `communication.detail_level`, `communication.visualization`, `tech_stack.language`, `work_style.debugging`

**Solution:** `solution.performance`, `solution.deployment`, `solution.infrastructure`, `solution.bug`

**Context:** `context.ownership`, `context.team`, `context.project`

### Handling Conflicting Memories

When user's preference changes:
1. Store new memory with higher confidence
2. Add `"supersedes": "old_memory_id"` field
3. Newer + higher confidence naturally ranks higher in search

### No Results on First Conversation

If `search_memory` returns empty:
1. Call a user/persona lookup tool (if available) for basic info (team, role)
2. Proceed with query
3. Store learnings for next time

### Recurring Issues Detection

When storing a solution, check if similar past solutions exist:

```
1. Search: "service-name issue-type solution"
2. Count matches with similar content
3. If count >= 2: This is recurring (occurrence #3+)
4. Add to metadata: "occurrence_count": 3, "pattern_detected": true
5. Alert user: "This is the 3rd time - consider permanent fix"
```

### Memory Lifecycle

**Versioning**: Store new memory with `supersedes` field when preferences change. Newer + higher confidence ranks higher naturally.

**Expiration**: For temporary context (projects with end dates, workarounds), add `"expires_at": "2026-06-30T00:00:00Z"` to metadata.

**Decay**: Solution memories don't decay (they're facts). Preference memories from 90+ days ago may need lower weight - filter by `created_at` if needed.

---

**End of Skill**
