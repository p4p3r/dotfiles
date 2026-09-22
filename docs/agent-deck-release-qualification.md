# Agent Deck release qualification

`agent-deck-release-qualify` is an offline, non-deploying release gate for an
Agent Deck candidate. It builds and runs only inside a temporary root and emits
one JSON verdict: `PASS`, `FAIL`, or `NOT_VERIFIED`.

The gate exercises behavior rather than searching for implementation strings:

- Codex pane classification rejects quoted `esc to interrupt` prose while
  accepting a later, structurally valid repeated occurrence.
- A freshly recreated conductor uses the runtime selected by its metadata and
  refuses absent, malformed, unreadable, invalid-UTF-8, or unsupported metadata.
- The candidate executable replaces an older bridge fixture, the resulting
  bridge is byte-for-byte the bridge embedded from that candidate, and the
  runtime probe imports that materialized copy.

No network or live Agent Deck state is used. `GOPROXY=off` and `GOSUMDB=off`
are forced. `HOME`, every XDG base, temporary directories, the Go build cache,
and `AGENT_DECK_CONDUCTOR_DIR` are rooted in a fresh temporary directory before
candidate code runs. Service and Python-package commands reached by isolated
`conductor setup` are inert stubs. Missing tools, cache misses, timeouts,
malformed probe output, and unavailable proof are `NOT_VERIFIED`, never a pass.
The Go module cache must be supplied explicitly; the harness never runs Go to
discover it before isolation. Go test approval requires structured proof that
the injected test and every exact subtest ran once and passed.

Run against an explicit prepared tree:

```sh
agent-deck-release-qualify \
  --source /path/to/prepared-agent-deck-tree \
  --go-mod-cache "$(go env GOMODCACHE)"
```

Or resolve an immutable tag or commit from a local repository and archive it
into the isolated root:

```sh
agent-deck-release-qualify \
  --repo /path/to/local-agent-deck \
  --ref v1.2.3 \
  --go-mod-cache "$(go env GOMODCACHE)"
```

Exit status is 0 for `PASS`, 1 for a verified behavioral `FAIL`, and 2 for
`NOT_VERIFIED`. The prewarmed module cache is read with network access disabled;
an absent dependency therefore produces `NOT_VERIFIED`.

The focused harness controls are:

```sh
TEST_ROOT="$(mktemp -d)"
mkdir -p "$TEST_ROOT"/{home,config,data,state,cache,tmp,conductor}
export HOME="$TEST_ROOT/home"
export XDG_CONFIG_HOME="$TEST_ROOT/config"
export XDG_DATA_HOME="$TEST_ROOT/data"
export XDG_STATE_HOME="$TEST_ROOT/state"
export XDG_CACHE_HOME="$TEST_ROOT/cache"
export TMPDIR="$TEST_ROOT/tmp" TMP="$TEST_ROOT/tmp" TEMP="$TEST_ROOT/tmp"
export AGENT_DECK_CONDUCTOR_DIR="$TEST_ROOT/conductor"
python3 -m unittest tests.test_agent_deck_release_qualification
private_dot_local/bin/executable_agent-deck-release-qualify --self-test
```
