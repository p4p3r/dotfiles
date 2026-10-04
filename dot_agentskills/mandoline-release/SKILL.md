---
name: mandoline-release
description: Cut a mandoline (engine) minor/patch release with scripts/release.sh, correctly re-embedding mandoline-packs, on this fish/nix/devenv-based box family. Use when asked to "cut a release", "release 0.x.y", "re-embed packs", or when scripts/release.sh fails on environment/toolchain errors (Bazel/Python, FFI artifact paths, direnv). Encodes real failures hit across four release attempts -- read this before improvising a fix.
metadata:
  version: "1.0.0"
  author: p4p3r
  tags: mandoline,release,packaging,rust,nix,direnv
  globs: ""
  alwaysApply: "false"
---

# Mandoline Release

Cutting a release is **outward-facing and hard to reverse** (a pushed tag, a published
artifact). Everything up to the point of pushing is reversible — treat it that way, but never
cross the line without the human's go-ahead.

## Non-negotiable discipline

1. **Reuse prior findings, don't re-derive them.** If earlier `RELEASE*-RESULTS.md` /
   `FIX-*-RESULTS.md` files exist in the conductor dir for this box, read them first. A blob
   SHA-256 or a load-gate count already verified twice does not need a third derivation.
2. **Stop and report before any irreversible step**: a release commit is fine to make locally,
   but **tag push, GitHub release publish, and artifact upload require explicit human sign-off**.
   If anything is unexpected or the docs disagree with the script, stop and report — do not
   improvise a workaround on your own judgment.
3. **A re-embed that produces a different blob SHA-256 than a previously-verified run is a STOP
   condition**, not something to shrug off — investigate before proceeding.
4. **Verify with real commands, never a self-report or a cached banner.** Re-run the actual gate
   command after every fix; don't assume a fix worked because the error message it was chasing
   is gone.

## 0. Prerequisites — before touching the release at all

- **Confirm every gating PR is actually merged**, on a fresh `git fetch`, in both
  `semgrep/mandoline` (engine) and `semgrep/mandoline-packs` (packs). Don't trust an earlier
  turn's memory of "merged" — merge queues can take minutes, and `gh pr merge --auto` reports
  success even while the PR is still queued.
- **Watch for matched engine/packs PR pairs.** Some packs PRs add metadata (a `kind` field, a new
  pattern shape) that a *specific* engine PR is the only consumer of. Embedding packs with the
  metadata but without the consuming engine code (or vice versa) ships an inert or inconsistent
  pair. If a packs PR's description says an engine PR "needs" it or "consumes" its output, treat
  them as one atomic unit — both merged, or neither embedded.
- **Confirm the target version.** `scripts/release.sh` manages the workspace version and
  path-dependency pins — don't hand-edit them. Diff the current workspace version against the
  newest stable tag to sanity-check whether this is really the minor/patch bump intended.

## 1. Activate the environment correctly — fish + direnv, not bare bash/zsh

This repo's toolchain (a pinned `rustup` Rust, and Bazel/Python tooling) is provisioned by a nix
flake via `.envrc` (`use flake ~/.config/private/nix/projects/semgrep/mandoline ...`). **Do not**
patch `PATH` by hand (`$HOME/.cargo/bin`, etc.) as your first move — that works around a symptom
and can silently diverge from the pinned toolchain the project actually intends.

```fish
cd <worktree-or-repo>
direnv allow          # see the worktree gotcha below — do this EVERY time
direnv exec . which cargo rustc python3    # confirms nix store paths, not /usr/bin or ~/.cargo
```

- **Every fresh git worktree needs its own `direnv allow`.** direnv's allow-list is keyed by
  path. `scripts/release.sh` (or any release attempt) creates a brand-new isolated worktree each
  run — it will **not** be pre-allowed, even if the main checkout is. Forgetting this step means
  `direnv exec` silently no-ops or a plain `cd` never loads the environment, and you fall back to
  whatever stray toolchain happens to be on `PATH` — which is how the FFI-path and cargo-not-found
  confusions happened in earlier attempts. Always run `direnv allow` in the worktree you're about
  to release from before relying on it.
- The worktree used for the actual release commit/tag/push must have local `main` checked out and
  be synchronized with `origin/main` — or the commit must be pushed with an explicit
  `HEAD:refs/heads/main` refspec. Never run the release from a feature-style branch name. Isolated
  worktrees remain the right pattern for packs compilation, FFI builds, and other preparation;
  use a local `main` checkout for the release commit and tag. `scripts/release.sh` now enforces
  this with a hard branch/synchronization guard and an explicit `HEAD:refs/heads/main` push.
- Prefer running the whole release flow as `direnv exec . scripts/release.sh <version>` (or,
  inside an interactive `fish -l` shell that has already `cd`'d into the allowed worktree, just
  `scripts/release.sh <version>` directly — direnv's shell hook loads automatically on `cd`).
- A one-shot `fish -l -c '...'` is fine for read-only checks. For anything long-running (the
  actual release), prefer a real fish session so you're not re-paying flake evaluation /
  `enterShell` cost or losing environment state between commands. `nix-direnv` caches the dev
  shell, so repeat loads are fast once warm.

## 2. The Bazel/Python gap direnv does NOT cover

`scripts/release.sh` runs `python3 tools/bazel/generate_build_files.py` to regenerate every
crate's `BUILD.bazel`. This needs `tree_sitter_rust`, which is **not** part of the nix flake's
Python (checked: `devenv.nix` has no python-package config at all) — you'll hit this even inside
a correctly direnv-activated shell.

`pip install --user -r tools/bazel/requirements.txt` **does not work on this box family**:
Debian's PEP-668 "externally managed environment" blocks a bare `pip install`, and separately
this system Python has `site.ENABLE_USER_SITE = False`, so even `--user` installs (if forced)
would not be picked up by a plain `python3` invocation.

**The fix — a dedicated venv, reused across releases:**

```bash
python3 -m venv ~/.venvs/mandoline-bazel
~/.venvs/mandoline-bazel/bin/pip install -r tools/bazel/requirements.txt   # tree-sitter==0.26.0, tree-sitter-rust==0.24.2 as of this writing — check the file for current pins
```

Check `~/.venvs/mandoline-bazel` for an existing venv before creating a new one — this is meant
to be a durable, box-local artifact, not recreated per release.

**Verify it actually resolves the failure** before trusting it (don't just install and hope):

```bash
PATH="$HOME/.venvs/mandoline-bazel/bin:$PATH" python3 tools/bazel/generate_build_files.py
# expect: "wrote N BUILD.bazel files for N local crates in the closure", exit 0
```

Then prepend that venv's `bin` to `PATH` for the **whole** `scripts/release.sh` invocation
(combine with the direnv-loaded shell from step 1 — direnv gives you cargo/rustc, the venv gives
you `tree_sitter_rust`; you need both at once):

```fish
direnv exec . env PATH="$HOME/.venvs/mandoline-bazel/bin:$PATH" scripts/release.sh <version>
```

If this is a throwaway verification run in a worktree you're about to discard anyway, running the
generator directly is harmless and reversible — it only rewrites generated `BUILD.bazel` files,
which `release.sh` stages itself later; nothing is committed by this step alone.

## 3. Own your `CARGO_TARGET_DIR`, and check disk before and during

A full workspace debug+release build (needed for FFI binding regeneration) can consume 20-25+
GiB in the target dir alone, on top of whatever else is running on the box. Concurrent fleet
children each get their own dedicated target dir by convention here, and disk has been exhausted
by this before.

- `export CARGO_TARGET_DIR=~/.cargo-target-release-<version>-<short-sha>` (or equivalent) before
  building — never build into the worktree's own `target/`.
- `df -h /home/paper` before starting, and periodically during a long build.
- **`scripts/release.sh`'s binding-regeneration step honors `CARGO_TARGET_DIR` as of engine PR
  #3043** (`fix(release): honor Cargo target directory`). Before that commit, it built into the
  dedicated dir but then looked for the FFI artifact at the hardcoded worktree-relative path
  `target/debug/libmandoline_ffi.so` and failed with "Debug library not found". If you hit that
  exact error, you're releasing from a commit older than #3043 — pull latest `main` rather than
  working around the path bug again.
- When a prior release attempt's PRs have since merged, its dedicated target dir is dead weight —
  confirm no live process references it (`pgrep -af <dirname>`), then reclaim it.

## 4. Re-embedding packs — the 2-step flow, and the real load gate

Re-embed is **two steps**, both required:

1. **Compile** the bundled packs from the exact clean packs commit you intend to ship:
   `compile-bundled-packs` (or the project's current equivalent binary/flag) against that commit.
2. **Patch** — the idempotent `--patch --output assets/default_packs.bin` step (this exists for
   MANDO-61). Run it, then **run it again** and confirm the SHA-256 is unchanged — that's your
   idempotence proof. Record both patch-run counts (language-scope patches, npm
   sink-qualification patches, or whatever the current patch categories are) in your report.

Run the **MANDO-61 regression tests** in the release profile after patching — do not skip these
because the patch step "looked" like a no-op.

**The real load gate** (this replaced an old, unreproducible "1287/1287 packs loading clean"
folklore figure — do not cite that number, derive fresh ones):

```bash
mandoline -q rml check <packs>/rml            # expect exit 0
mandoline -q rml check <packs>/dependencies   # expect exit 0
```

Both must exit 0. Additionally, **total rule definitions must equal distinct rule IDs** — that
equality is the arithmetic proof there are no duplicate/colliding rule IDs in what you're about
to ship. If they differ, there's a real collision; do not embed until it's fixed (see the packs
repo's own contribution docs for how rule IDs are namespaced).

`min_engine` is a **real gate that bites at re-embed time, not at merge time**: a pack whose
`min_engine` is newer than the engine version errors (exit 2) on `rml run`/`load_dir` paths, and
only *skips* on embedded paths — so a pack can merge cleanly into `mandoline-packs` and still
break this release. Explicitly check that every pack's `min_engine` constraint is satisfied by
the engine version you're cutting, don't assume it from the fact that CI was green on the PR.

**Engine PR #3041 changed loader behaviour**: a directory entry that looks like it was meant to
be RML but can't be classified is now **surfaced** as an `rml-file-unclassified` warning (with
path and reason) instead of being silently skipped. If new warnings appear during your load-gate
run that weren't in a prior verified run, **report them with counts** — do not treat them as a
failure, and do not suppress or ignore them; they may be revealing a real, previously-invisible
problem the same way this exact mechanism did during development.

## 5. Report before crossing the irreversible line

Once the release commit is prepared locally (version bump, changelog, regenerated bindings/BUILD
files, the packs re-embed commit), **stop and show the human the diff / intended commit and tag**
before:
- pushing the release commit to a shared branch other agents/CI will see as canonical,
- pushing the version tag,
- publishing a GitHub release or uploading any artifact.

A version bump, a re-embed commit, and regenerated files sitting on a local branch in an isolated
worktree are all cheap to throw away. A pushed tag is not.

## Known-fixed issues (don't rediscover these)

- **#3020** — `shape = "attribute"` pack rows are IR-only; legacy's resolved source-pattern list
  is provably byte-identical whether or not a row carries `shape`. Re-lowering a pack row this way
  does not require a legacy-side audit.
- **#3041** — unclassifiable directory entries during `rml check`/`rml run` are surfaced as
  warnings, never silently skipped (see §4).
- **#3043** — `scripts/release.sh` binding regeneration honors `CARGO_TARGET_DIR` (12 artifact-path
  sites fixed across local/stable/canary/customer/XCFramework release tooling). If you hit a
  hardcoded `target/debug/...` path failure again, that's either a regression or a 13th site —
  find it and fix it the same way, don't hand-patch around it.
- **v0.16.1 main-ref incident** — the release was run from an isolated worktree on a feature-style
  branch. `git push origin HEAD` pushed the release commit to that branch's same-named remote ref,
  silently leaving `main` behind and skipping push-to-main automation, specifically `docker.yml`'s
  ECR publish. The structural fix in engine PR #3112 requires a synchronized local `main` checkout
  before release changes and pushes the commit explicitly to `refs/heads/main`; keep release
  preparation in isolated worktrees, but perform the release commit/tag/push from local `main`.
