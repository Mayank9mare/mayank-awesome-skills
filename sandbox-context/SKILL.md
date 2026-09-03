---
description: Generic skill for Daytona sandbox context management. Provides sandbox lifecycle management, session-based persistence, and workspace operations for agents running in sandbox environments.
---

# Sandbox Context Management

This skill provides standardized patterns for managing Daytona sandbox environments across agent sessions.

## When This Skill Applies

Use this skill when:
- Agent has `"use_sandbox": true` in metadata
- Agent needs to execute bash, docker, or git operations in an isolated environment
- Agent needs to persist sandbox across conversation turns or resumed sessions

## Sandbox Lifecycle

### Step 1: Check for Existing Sandbox

**On every task start, check if a sandbox already exists for this session:**

Use Daytona MCP tool to check:
```
get_sandbox(session_id=<current_session_id>)
```

- If sandbox exists → Use that `sandbox_id` for all operations
- If no sandbox found → Proceed to Step 2

### Step 2: Create Sandbox (If Needed)

Use Daytona MCP tool to create:
```
create_sandbox(session_id=<current_session_id>)
```

Store the returned `sandbox_id` for use in all subsequent operations.

### Step 3: Persist Sandbox ID

**Save sandbox_id to workspace for session resumption:**

Write to `.sandbox_id` file in current working directory:
```bash
echo "<sandbox_id>" > .sandbox_id
```

### Step 4: Validate Workspace

**CRITICAL: Workspace directories may not exist. Always create them first:**

```bash
mkdir -p /workspace
mkdir -p /workspace/{service_name}
```

## Session Resumption

When a session is resumed (same `session_id`):

1. Check if `.sandbox_id` file exists in workspace
2. Read the sandbox_id: `cat .sandbox_id`
3. Validate sandbox is still active using `get_sandbox(sandbox_id)`
4. If valid → reuse it
5. If invalid/gone → create new sandbox and update `.sandbox_id`

## Sandbox Capabilities

The sandbox supports:

| Capability | Description |
|------------|-------------|
| **Bash** | All standard Linux commands, file operations, process management |
| **Docker** | Build images, run containers, docker-compose |
| **Git** | Clone, checkout, commit (use git-operations MCP for GitHub push/PR) |

## File Operations

### Reading Files

```bash
# Simple read
cat /path/to/file.txt

# Check if exists, then read
[ -f /path/to/file.txt ] && cat /path/to/file.txt

# Read first/last N lines
head -50 /path/to/file.txt
tail -50 /path/to/file.txt
```

### Writing Files

```bash
# Step 1: Create directory (ALWAYS do this first)
mkdir -p /path/to/directory

# Step 2: Write file using heredoc (use 'EOF' with quotes to preserve $variables)
cat > /path/to/file.txt << 'EOF'
Your content here
$variables stay as literals
Multiple lines supported
EOF

# Step 3: Verify (optional but recommended)
[ -s /path/to/file.txt ] && echo "Success" || echo "Failed"
```

### Quick Reference

| Operation | Command |
|-----------|---------|
| Create directory | `mkdir -p /path/to/dir` |
| Write file | `cat > file.txt << 'EOF'`...`EOF` |
| Read file | `cat file.txt` |
| Check exists | `[ -f file.txt ] && echo "yes"` |
| Check not empty | `[ -s file.txt ] && echo "has content"` |
| List directory | `ls -la /path/to/dir` |
| Copy file | `cp source.txt dest.txt` |
| Move/rename | `mv old.txt new.txt` |
| Delete file | `rm file.txt` |
| Delete directory | `rm -rf /path/to/dir` |

## Docker Operations

```bash
# Build image
docker build -t my-image .

# Run container
docker run -d --name my-container my-image

# Docker compose
docker-compose up -d

# View logs
docker logs my-container

# Stop/remove
docker stop my-container && docker rm my-container
```

## Error Handling

Return structured JSON on errors:
```json
{
  "status": "FAILED",
  "phase": "sandbox_creation",
  "reason": "Failed to create Daytona sandbox",
  "recoverable": true
}
```

## Best Practices

1. **Always `mkdir -p` first** - directories may not exist
2. **Use quoted heredocs** - `<< 'EOF'` preserves $variables as literals
3. **Persist sandbox_id** - save to `.sandbox_id` for session resumption
4. **Validate on resume** - check if stored sandbox still exists
5. **Use git-operations MCP** - for GitHub authenticated operations (push, PR)

## Workflow Diagram

```
Task Starts
    │
    ▼
Check sandbox exists? ──► get_sandbox(session_id)
    │
    ├─► YES: Use existing sandbox_id
    │
    └─► NO: Create sandbox ──► create_sandbox(session_id)
                │
                ▼
         Save to .sandbox_id
                │
                ▼
    Create directories (mkdir -p /workspace/...)
                │
                ▼
    Execute task operations
```
