# Signed ingress candidate

`agent-deck-signed-ingress` admits signed GitHub pull-request and Linear Issue deliveries into one
host-local SQLite ledger. The process binds only `127.0.0.1` and an owner-only Unix socket. TLS and
any external relay require separate configuration and authority. This public module is disabled by
default; building it does not deploy it.

Signatures cover exact raw bytes and are compared in constant time before parsing. GitHub supports
`opened`, `reopened`, `synchronize`, `edited`, and `closed`; configuration selects a non-empty subset.
Repository, sender, and pull-request IDs are canonical positive integers. See GitHub's
[signature validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries),
[delivery guidance](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks),
and [payload contracts](https://docs.github.com/en/webhooks/webhook-events-and-payloads).

Linear supports only `Issue` with selected `create`, `update`, and `remove` actions. `data.id`,
`data.teamId`, `data.projectId`, and `actor.id` must be non-empty canonical lowercase UUID strings.
Missing or null projects fall outside project-owned scope and are rejected. The Linear-owned
[integration guide](https://github.com/linear/linear-solutions/blob/main/integration_guides/scenarios/03-webhooks/README.md)
defines these Issue field paths, and the [SDK types](https://github.com/linear/linear/blob/master/packages/sdk/src/webhooks/types.ts)
map Issue events. The signed integer `webhookTimestamp` is the freshness authority. Both ±60,000 ms
boundaries are accepted; adjacent milliseconds are rejected, matching the
[official verification example](https://linear.app/developers/webhooks). This candidate additionally
requires `Linear-Timestamp == str(webhookTimestamp)` as a separate fail-closed local binding;
that equality is local policy, not an official provider guarantee.
Only canonical UUIDv4 Linear delivery IDs are admitted.

Every HTTP request has a two-second absolute read deadline, a 256 KiB body cap, at most 48 headers,
2 KiB header lines, and 16 KiB total request line/header bytes. Only exact POST paths with JSON media
type and one canonical positive content length are accepted. Duplicate headers, folded lines,
transfer/content encoding, trailers, expectation negotiation, malformed JSON, duplicate JSON keys,
non-finite numbers, wrong scalar types, and unsupported actions fail closed. Each listener has eight
handler slots; the writer queue has 32 entries and a three-second response bound. Overload can close
the connection or return 503, without a successful receipt.

One daemon thread owns all database access. Only a fixed body-free envelope crosses to it. Rows
contain codes, opaque aliases, declared owners, UTC lifecycle times, and state/result enums. Provider
IDs, names, text, URLs, and bodies never enter the ledger, control protocol, logs, or commands.
Startup requires the exact compiled version-2 schema, including the compact tombstone table's
columns, constraints, and indexes; changed or version-1 ledgers fail closed without implicit
migration. Listing uses explicit body-free columns and a bounded row limit.
Core dumps and default request/error logging are disabled. Secret values are read from distinct
owner-only regular files without following symlinks; their bytes are used exactly, including any
newline. Neither secrets nor config are accepted from environment values or the Nix store.

The stable alias key is exactly 32 raw random bytes, distinct from both signing secrets. Aliases use
full HMAC-SHA256 with versioned event/object/key domains, four-byte big-endian length-prefixed ASCII
components, and lower-case unpadded base32 encoding (52 characters). Event components are provider
and canonical delivery ID; object components are provider, normalized object type, and canonical
object ID. Preserve this key with the ledger. Startup rejects changed alias keys or owners;
signing-secret rotation preserves identity. A subscription change requires an explicit scope/ledger
decision.

HTTP 200 follows authentication, freshness, allowlists, normalization, capacity, and a durable
SQLite commit. Duplicate lookup precedes capacity checks and returns the immutable event alias.
Before-commit failure leaves no accepted row. After-commit response loss is resolved by retry.
Delivery headers are provider identifiers, not additional signed body fields. GitHub supplies no
signed delivery timestamp, so replay suppression lasts while its alias is retained. Completed-row
pruning atomically replaces the full row with an owner-bound tombstone containing only the event
alias and terminal state/result. A retry returns that original terminal disposition and cannot be
claimed again. Active rows plus tombstones share the configured capacity, so retained identity is
bounded without evicting replay protection. Distinct deliveries on one object remain distinct
ledger work; reordering never rewrites an existing delivery.

The transition graph is `accepted -> claimed -> completed | uncertain | dead_letter`. Claim uses a
transactional compare-and-set. A crash preserves `claimed` for explicit reconciliation. `api_unavailable`
and `indeterminate` settle to `uncertain`; the companion performs no consumer/provider calls. Only
completed rows strictly older than the configured horizon can be compacted. Accepted, claimed,
uncertain, and dead-letter rows are never pruned; they and the tombstones retain replay protection
and consume capacity.

Supply one mode-0600 strict JSON config outside the store. All keys shown below are required;
unknown keys and duplicate/empty allowlist members are rejected. This example uses synthetic IDs
and file references only. Create the directories containing those files with mode 0700 and keep
config, signing-secret files, and the alias-key file at mode 0600, with no symlinks or hard links.
The daemon creates the final state/runtime directories when their existing parent is available.

```json
{
  "version": 1,
  "owner": {"host": "fixture-host", "conductor": "0123abcd-1700000000"},
  "listen": "127.0.0.1",
  "port": 8787,
  "state_dir": "/home/example/.local/state/agent-deck-signed-ingress",
  "runtime_dir": "/run/user/1000/agent-deck-signed-ingress",
  "alias_key_file": "/run/fixture-secrets/alias-key",
  "capacity": 10000,
  "retention_seconds": 2592000,
  "github": {
    "path": "/github",
    "owner": {"host": "fixture-host", "conductor": "0123abcd-1700000000"},
    "secret_file": "/run/fixture-secrets/github-signing",
    "actions": ["opened", "reopened", "synchronize", "edited", "closed"],
    "repository_ids": [1001],
    "actor_ids": [2001]
  },
  "linear": {
    "path": "/linear",
    "owner": {"host": "fixture-host", "conductor": "0123abcd-1700000000"},
    "secret_file": "/run/fixture-secrets/linear-signing",
    "actions": ["create", "update", "remove"],
    "team_ids": ["00000000-0000-4000-8000-000000000002"],
    "project_ids": ["00000000-0000-4000-8000-000000000003"],
    "actor_ids": ["00000000-0000-4000-8000-000000000004"]
  }
}
```

The Linux Home Manager seam exposes only `enable` and `runtimeConfig`, plus a read-only package.
An enabled service requires `listen` to be exactly `127.0.0.1` and config state/runtime paths to
match systemd's managed `%S/agent-deck-signed-ingress` and `%t/agent-deck-signed-ingress`
directories. It passes only the config path in argv, projects no environment secrets, uses
`UMask=0077`, mode-0700 directories, mode-0600 socket/files, an IPv4-only address-family sandbox,
ten-second start/stop bounds, and at most three restarts per five minutes.

```nix
programs.agent-deck-signed-ingress = {
  enable = true;
  runtimeConfig = "/run/fixture-config/signed-ingress.json";
};
```

Run the daemon with `agent-deck-signed-ingress --config /absolute/config.json serve`. All clients
use `--socket /absolute/runtime/control.sock`; they never open SQLite. The four control operations
are `list --limit N` (1–100), `claim EVENT_ALIAS`, `settle EVENT_ALIAS --result RESULT`, and `prune`.
Settlement results are `completed`, `api_unavailable`, `indeterminate`, and `dead_letter`.
The one-line JSON wire protocol carries the corresponding `op`, `event_alias`, `result`, or
`limit` fields, with a 1 KiB request cap. Linux peer credentials must match the daemon owner.
Listing orders by acceptance time and alias and returns at most 100 rows; claim a specific alias
only after the consumer has obtained the owner-bound packet through its separately authorized flow.

Verification uses isolated temporary HOME/XDG/state and synthetic fixtures:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
nix build --offline --no-link ./nix#checks.x86_64-linux.signed-ingress
nix build --offline --no-link ./nix#packages.x86_64-linux.agent-deck-signed-ingress
```

These checks neither activate the generated unit nor prove public reachability or live provider
registration. No Agent Deck wake, provider API fetch, or external effect is implemented.
