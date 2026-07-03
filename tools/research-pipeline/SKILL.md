---
name: research-pipeline
description: Deep research on any topic using YouTube search + NotebookLM analysis. Collects 7-20 curated video URLs (5-tier by recency + views), feeds to NotebookLM, returns distilled knowledge at ~1500 tokens instead of 100K+.
allowed-tools: Bash(python *), Bash(notebooklm *)
---

# Research Pipeline

Token-efficient deep research. Chains YouTube search (zero tokens) into NotebookLM (Google's tokens) and reads back a distilled summary (~1500 Claude tokens for what would normally cost 100K-500K).

## CRITICAL RULES

1. **7 minimum, 20 maximum sources.** Never exceed 20. NotebookLM free tier has limits.
2. **No `add-research` command.** It adds hundreds of sources uncontrollably. Only use manual `source add` with curated URLs from yt_search.py.
3. **Deduplicate before adding.** Never add the same URL twice. The script handles dedup internally.
4. **One notebook per topic.** Check if a relevant notebook exists before creating new.
5. **Verify notebook context** before adding sources. Run `notebooklm use <id>` first.

## Search Tiers

The yt_search.py script searches in 5 tiers, stopping when it has enough:

| Tier | Window | Purpose |
|------|--------|---------|
| 1 | Last 7 days | Breaking/trending content |
| 2 | Last 30 days | Recent coverage |
| 3 | Last 90 days | Quarter's best |
| 4 | Last 12 months | Annual proven content |
| 5 | All time | Classics with high views |

Skips videos under 2 minutes (shorts/ads). Deduplicates across all tiers.

## Instructions

### Step 1: Get the topic
Take from `$ARGUMENTS`. If none, ask user.

### Step 2: Search YouTube
```bash
python "<this skill's base directory>/yt_search.py" <topic>
```

### Step 3: Create NotebookLM notebook
```bash
notebooklm create "Research: <topic>" --json
notebooklm use <notebook_id>
```

### Step 4: Add URLs as sources (MAX 20)
```bash
PYTHONIOENCODING=utf-8 notebooklm source add "<url>" --json
```

### Step 5: Wait for processing
```bash
PYTHONIOENCODING=utf-8 notebooklm source list --json
```
Wait until all `ready`. Max 5 checks, 30s apart.

### Step 6: Query
```bash
PYTHONIOENCODING=utf-8 notebooklm ask "<question>" --json
```

### Step 7: Return results
Distilled answer + source count + notebook ID.

## Environment (Windows)
Always use `PYTHONIOENCODING=utf-8` prefix for notebooklm commands.

## Token Economics
| Step | Cost |
|------|------|
| YouTube search | 0 |
| NotebookLM | 0 (Google) |
| Reading summary | ~500-1500 |
| **Total** | **~1500 tokens** |
