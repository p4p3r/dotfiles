---
name: agent-deck-cleanup
description: Reclaim disk and tidy an agent-deck fleet — retire dead sessions, remove spent worktrees, clear build-cache scratch — without destroying unpushed work. Survey, archive, then delete.
metadata:
  version: "1.0.0"
  author: p4p3r
  tags: agent-deck,cleanup,worktrees,sessions,disk
  globs: ""
  alwaysApply: "false"
---

# agent-deck cleanup

Fleets accumulate. Sessions outlive their task, worktrees outlive their PR, and build caches dwarf
everything else. This reclaims that space **without losing work**.

The governing rule: **survey → archive → delete, in that order.** Never delete on an assumption. If
what you find contradicts how something was described to you, report it instead of proceeding.

## The one fact that makes this safe

`git worktree remove` **does not delete the branch.** Committed work survives; the branch ref keeps
it. So the *only* things at risk are:

1. **untracked files** — never in git at all
2. **uncommitted modifications** to tracked files

Everything else is recoverable. That is why the archive step is narrow and cheap, and why "this
worktree has 26 unpushed commits" is usually a *non-issue* — those commits are on the branch.

## Phase 1 — survey, change nothing

Sessions. **Read `parent_session_id` from `session show --json`, never `list --json`** — `list` omits
the key entirely, so a `// "NONE"` default reads NONE for every session whether linked or not.

```bash
agent-deck list --json | python3 -c "
import json,sys,os
for s in json.load(sys.stdin):
    print(f\"{s['status']:9} {s['group']:20} {s['title']:34} dir_exists={os.path.isdir(s['path'])}\")"
```

Worktrees — **across every repo, not just the obvious one.** Worktrees of other repos can live under a
shared `.worktrees/` directory and are easy to miss; they are often the largest items.

```bash
# per repo
git -C <repo> worktree list --porcelain | awk '/^worktree /{print $2}'
# for each worktree: is anything actually at risk?
git -C <wt> status --porcelain | wc -l                  # dirty files
git -C <wt> log --oneline HEAD --not --remotes | wc -l  # commits on NO remote
git -C <wt> branch --show-current
```

Also check, per worktree, whether its PR is merged/closed and whether the branch is an ancestor of the
default branch. A **squash-merged** PR leaves the branch *not* an ancestor even though its content
landed — so "not merged" by ancestry is not evidence the work is unlanded. Check PR state too.

Disk. Find the real consumers before deciding anything:

```bash
du -sh <worktrees-root>/* 2>/dev/null | sort -h | tail -20
du -sh /tmp/<agent-scratch-root>/* 2>/dev/null | sort -h | tail -20
```

## Phase 2 — archive what deletion would actually destroy

Only for worktrees with dirty files. Preserve untracked content verbatim, tracked edits as a patch,
plus the branch name and the list of commits not on any remote:

```bash
ARCH=~/.local/share/wf-worktree-archive/$(date +%F)   # pass the date in; do not rely on it being available
mkdir -p "$ARCH/<name>"
git -C <wt> status --porcelain            > "$ARCH/<name>/_status.txt"
git -C <wt> diff                          > "$ARCH/<name>/_tracked-modifications.patch"
git -C <wt> log --oneline HEAD --not --remotes > "$ARCH/<name>/_commits-not-on-any-remote.txt"
git -C <wt> branch --show-current          > "$ARCH/<name>/_branch.txt"
git -C <wt> ls-files --others --exclude-standard -z | while IFS= read -r -d '' f; do
  mkdir -p "$ARCH/<name>/untracked/$(dirname "$f")"
  cp -a "<wt>/$f" "$ARCH/<name>/untracked/$f"
done
```

**Then look at what you archived.** Analysis write-ups, labelled corpora, eval outputs and generated
reports are frequently untracked — that is exactly the material worth keeping, and it is invisible to
`git log`. If the archive contains something that looks like a deliverable, say so before deleting.

## Phase 3 — delete, narrowest first

**Worktrees** — safe when clean, or after archiving:

```bash
git -C <repo> worktree remove --force <path>
git -C <repo> worktree prune
```

Run `worktree remove` from **the owning repo**. Then confirm the branches you cared about still
resolve: `git -C <repo> rev-parse --short <branch>`.

**Sessions** — remove those whose working directory no longer exists (they are broken regardless), and
those whose task is demonstrably finished:

```bash
agent-deck remove <title-or-id>      # note: `remove`, and there is no --force flag
```

Keep any session that is `running`, that holds context you may still need, or whose PR is open and
unmerged. Removing a session discards its conversation.

**Temp storage** — build caches are usually the whole win. A Rust `target/` or a
`node_modules` under an agent scratchpad can be tens of GB and is pure cache.

```bash
du -ah <scratch>/<session> | sort -h | tail -10   # find the actual weight first
```

Only delete scratchpads belonging to sessions you removed, or whose contents you have identified as
build cache.

## Never delete without asking

- **Resumable evaluation state** — harness directories holding `results/`, `oracle/`, pinned binaries.
  These look like junk by size and are irreplaceable.
- **Labelled corpora, golden files, adjudication records.**
- Anything under a path the user has named as protected.
- Any worktree whose repo the user has placed behind a "don't touch" rule — surveying is fine,
  deleting is not.

If a candidate is large *and* you cannot explain what it is, that is a reason to ask, not to delete.

## Shell traps that have cost real time here

- **Paths beginning with `-`** are parsed as flags. `du`/`rm` need a `./` prefix or `--`:
  `rm -rf -- "./-home-paper-Code-..."`.
- **`zsh` eats `"$VAR:path"`** as a `:s` substitution modifier. Always brace: `"${VAR}:path"`.
- **Verify the file list resolved before trusting a scan.** A loop over wrong paths where `[ -f ]` is
  false for every entry reports "clean" having examined nothing. Print the list you are about to scan.
- **Sanity-check impossible numbers.** An intersection larger than the smaller set, a directory
  bigger than its filesystem — recompute before reporting.

## Report

State plainly:

| | |
|---|---|
| Reclaimed | before → after, for disk and for counts |
| Removed | worktrees, sessions, scratch dirs |
| Archived | what, and the exact path |
| **Kept deliberately** | and why — this is the most useful line |
| Needs a decision | anything large-and-unexplained, or behind a protection rule |

Confirm explicitly that the branches behind removed worktrees still resolve. "Nothing was lost" is a
claim to be evidenced, not asserted.
