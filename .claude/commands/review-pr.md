---
allowed-tools: Bash(gh:*), Read, Edit, Write
description: Interactively review PR comments one at a time
argument-hint: <pr-number|latest>
---

Review PR #$1 interactively. If "$1" is "latest", find the most recent PR for the current branch using `gh pr list --head $(git branch --show-current) --json number -q '.[0].number'`.

## Step 1: Fetch PR Info and Display Summary Table

First, get the repo owner/name:
```bash
gh repo view --json owner,name -q '"\(.owner.login)/\(.name)"'
```

Then fetch all review threads using GraphQL (this gets resolved status, outdated status, and replies):
```bash
gh api graphql -f query='
{
  repository(owner: "OWNER", name: "REPO") {
    pullRequest(number: PR_NUMBER) {
      title
      reviewThreads(first: 100) {
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          comments(first: 10) {
            nodes {
              id
              body
              author { login }
              createdAt
            }
          }
        }
      }
    }
  }
}'
```

Display the summary table IMMEDIATELY before any review:

```
PR #52: <title>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
N comments from Copilot · X resolved · Y outdated

 # | File                 | Line | Issue                                    | Status
---|----------------------|------|------------------------------------------|------------------
 1 | selectors.py         |    — | Data slice inconsistency in send()       | Resolved, outdated
 2 | http_logging.py      |  210 | First recv latency uses wrong baseline   | Resolved
...

Review comment #1?
```

**Status column rules:**
- `Resolved` — marked resolved in GitHub
- `Outdated` — code changed since comment was made
- `→ #N` — reply references issue #N
- `N replies` — has followup discussion
- *(blank)* — unresolved, needs attention

**Issue summary:** Generate a ~40 char summary of Copilot's objection from the comment body.

**For outdated comments:** Check if the code change actually addressed the issue or if it's still relevant. Note this in your review.

## Step 2: Interactive Review

After showing the table, automatically start with the first unresolved, non-outdated comment. Don't wait for user to pick.

For each comment:
1. Show the full comment context (file, line, code snippet, full comment body)
2. Read the relevant code to understand current state
3. Give your opinion FIRST: agree, disagree, or partially agree with reasoning
4. Wait for user decision before taking action
5. Possible actions: fix it, create issue, dismiss, or discuss further

## Step 3: After Each Fix

After EVERY fix, immediately create a commit on the PR's feature branch:

1. Stage only the files changed for this fix
2. Commit with a normal commit message describing the change (do NOT reference review comment numbers like #6 — those look like issue references):
   ```
   Fix logger propagation in HttpLoggingInstrument

   Default logger now sets propagate=False to avoid duplicating
   logs to parent handlers.

   Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
   ```
3. Don't batch multiple fixes into one commit — each fix gets its own commit

## Step 4: Reply and Resolve Thread

After committing, use the `pr-resolve` script to reply to the thread and mark it resolved:

```bash
.claude/scripts/pr-resolve <thread-id> <commit-sha>
```

The script will:
- Validate the thread exists and show a preview
- Post a reply with the commit SHA (auto-linked by GitHub) and "-bot" on a new line
- Mark the thread as resolved
- Require confirmation (unless `--yes` is passed)

Get the thread ID from the GraphQL query in Step 1 (the `id` field of each reviewThread).

Then continue to the next comment.

## Key Principles

- Opinion first, implementation second
- It's okay to disagree with reviewers—explain your reasoning
- Out-of-scope issues → create GitHub issues, don't ignore them
- Use plan mode for API changes or architectural decisions
- For outdated comments, do extra diligence to verify if truly resolved
