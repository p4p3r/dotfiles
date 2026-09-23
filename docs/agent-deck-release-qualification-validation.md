# Agent Deck release-qualification validation

Validation was run offline on 2026-09-22 with a prewarmed Go module cache. The
local upstream repository and public dotfiles worktree were clean before the
matrix. `v1.16.16^{commit}` resolved to
`05ff0a4cd9b2b4e7ed9ce898c35b0ba57cefd86e`.

The immutable-source commands were:

```sh
UPSTREAM=/path/to/local/agent-deck
HARNESS_REPO=/path/to/public-dotfiles-worktree
GO_MOD_CACHE="$(go env GOMODCACHE)"

"$HARNESS_REPO/private_dot_local/bin/executable_agent-deck-release-qualify" \
  --repo "$UPSTREAM" --ref v1.16.16 \
  --go-mod-cache "$GO_MOD_CACHE" --timeout-seconds 600

"$HARNESS_REPO/private_dot_local/bin/executable_agent-deck-release-qualify" \
  --repo "$UPSTREAM" \
  --ref 8a2ef5d3b118e7d0e10fee938d60bd61cb443c66 \
  --go-mod-cache "$GO_MOD_CACHE" --timeout-seconds 600

"$HARNESS_REPO/private_dot_local/bin/executable_agent-deck-release-qualify" \
  --repo "$UPSTREAM" \
  --ref c4866e696fe1318fc5622ad83ea3a54a8f31373a \
  --go-mod-cache "$GO_MOD_CACHE" --timeout-seconds 600
```

Observed verdicts:

| Candidate | Busy provenance | Bridge materialization | Runtime recreation | Overall |
| --- | --- | --- | --- | --- |
| official `v1.16.16` | `FAIL` | `PASS` | `FAIL` | `FAIL` |
| PR #2353 head `8a2ef5d3` | `PASS` | `PASS` | `FAIL` | `FAIL` |
| PR #2354 head `c4866e69` | `FAIL` | `PASS` | `PASS` | `FAIL` |

The v1.16.16 busy probe observed both quoted-prose cases as busy. Its runtime
probe failed the metadata-selected Codex case and all missing, malformed,
unreadable, invalid-UTF-8, and unsupported-runtime fail-closed cases. PR #2353
passed the busy gate, and PR #2354 passed all runtime cases. Each single-PR
head correctly
remained an overall failure because it does not contain the other safeguard.

The Go-proof integrity control also reran PR #2353 with
`SOFTKILL_TEST_HELPER=eof_clean` inherited. The gate removed the helper selector
and reported structured `run` plus `pass` proof for the injected top-level test
and all four exact subtests. The focused controls additionally verified that an
empty exit-0 `/usr/bin/true` instrument is `NOT_VERIFIED`, skipped tests are not
proof, and omitting `--go-mod-cache` does not execute Go.

The two PR heads were also combined without a branch or commit:

```sh
SCRATCH="$(mktemp -d)"
git -C "$UPSTREAM" worktree add --detach "$SCRATCH/tree" \
  8a2ef5d3b118e7d0e10fee938d60bd61cb443c66
git -C "$SCRATCH/tree" merge --no-commit --no-ff \
  c4866e696fe1318fc5622ad83ea3a54a8f31373a
git -C "$SCRATCH/tree" rev-parse HEAD MERGE_HEAD
"$HARNESS_REPO/private_dot_local/bin/executable_agent-deck-release-qualify" \
  --source "$SCRATCH/tree" \
  --go-mod-cache "$GO_MOD_CACHE" --timeout-seconds 600
git -C "$UPSTREAM" worktree remove --force "$SCRATCH/tree"
rmdir "$SCRATCH"
```

`HEAD` and `MERGE_HEAD` printed the exact PR #2353 and PR #2354 hashes above.
The combined scratch tree returned `PASS` for all three gates. Its materialized
bridge SHA-256 was
`5371e6b5cecb49d3ddc105ff39597960e4aba8486abd05580cc71814b304d92e`.
Both source commits verified as good SSH signatures by the configured signing
identity.

After cleanup, the upstream repository and both PR worktrees were still clean.
The live bridge log's `inode:size:mtime` tuple was unchanged across the matrix;
no installed binary, bridge, service, configuration, or session was used or
mutated.
