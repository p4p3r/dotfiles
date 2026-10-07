# Fake-only PR-warden controller

`agent-deck-pr-warden-controller` connects one accepted signed-ingress pull-request object to one
host-local Agent Deck specialist lifecycle. It is generic source, disabled by default, and has no
GitHub network adapter. Building the package or module performs no admission, session action,
provider request, activation, or service start.

Signed ingress remains the sole authority for delivery identity, replay suppression, claim, and
settlement. The controller never opens the ingress database and keeps no event queue, seen set, or
consumed-event ledger. Its only lifecycle authority is one owner-only `lifecycle.json`, plus one
result and compact handoff artifact per exact trigger.

## Commands and ordering

All commands take only `--config /absolute/owner-only.json` and one operation:

- `admit` writes `ADMITTED` with `CONDUCTOR` ownership, launches one parentless specialist with
  `--acceptance-only`, validates the complete body-free receipt, and requires an exact-ID
  `session show`. If that owner is still running, the lifecycle remains `ACTIVE`; a later `tick` or
  `reconcile` verifies the same owner and admission result, consumes the admission trigger, and
  moves the same immutable owner to `WAITING` without another turn.
- `tick` takes a nonblocking single-writer lock, reconciles existing work, validates the exact
  owner, lists at most 100 ingress rows, and claims the first matching accepted alias before any
  wake. An unchanged heartbeat may update a checked timestamp but sends no turn.
- `reconcile` compares the one current trigger with the ingress ledger and result artifact. It can
  settle a verified result or move a terminal ledger row forward, but never resends a claimed,
  attempted, submitted, uncertain, or terminal trigger.

The wake order is fixed: exact owner observation; ingress `claim`; durable lifecycle attachment;
durable `ATTEMPTED`; one `session send --acceptance-only`; durable exact receipt; private result
validation; fresh fake-provider and fake-local-git observations; ingress `settle`; lifecycle
disposition. A crash cannot turn missing controller evidence into permission to resend.

An exact result artifact is named `<event-alias>.json`, is mode `0600`, and contains exactly:
`schema_version`, `trigger_alias`, `object_alias`, `owner_session_id`, `status`, `result_code`,
`completed_at`, `provider_code`, and `local_git_code`. It contains no event body, PR/review text,
check output, transcript, raw provider response, token, or log. The controller writes a separate
compact handoff with bounded codes and references after independently checking current facts.

## Deterministic dispositions

- `OPEN` with an exact clean local head settles `completed` and returns to `WAITING`.
- `API_UNAVAILABLE` settles `api_unavailable`, enters `ESCALATED`, and is never retried.
- malformed or identity-mismatched current facts settle `indeterminate` when that settlement is
  verifiable, enter `ESCALATED`, and are never retried.
- stale provider/local head, dirty or untracked worktree, unpushed commits, or a changed local
  binding produces a bounded escalation. The trigger may settle `completed` because its read-only
  report was handled; no git or provider mutation follows.
- closed without merge settles the handled trigger, retains the owner, enters `ESCALATED`, and
  requires a user decision.
- merged state first settles the trigger and proves no matching accepted or claimed row remains.
  Only an exact retained-session archive response and a same-ID `stopped` observation clear the
  owner and enter `ARCHIVED`.

An owner observed as `running` or `queued` leaves a matching event accepted and unclaimed. A
stopped, error, missing, or wrong-ID owner escalates; the controller never calls `session start`,
`session restart`, or a replacement launch. A full 100-row foreign page cannot prove absence and
escalates as `LIST_BOUND_NOT_VERIFIED`.

## Private runtime configuration

The configuration must be a regular mode-`0600`, single-link file owned by the effective user,
outside the Nix store. Every state, runtime, result, and handoff directory is distinct, absolute,
non-symlinked, owner-owned, and mode `0700`. The controller creates only the final directories and
writes files mode `0600` using durable atomic replacement.

The strict version-1 shape is illustrated with synthetic fixture values only:

```json
{
  "schema_version": 1,
  "service_instance": "fixture-instance",
  "work_id": "fixture-work",
  "owner": {"host": "fixture-host", "conductor": "0123abcd-1700000000"},
  "paths": {
    "state_dir": "/run/fixture/state",
    "runtime_dir": "/run/fixture/runtime",
    "result_dir": "/run/fixture/results",
    "handoff_dir": "/run/fixture/handoffs"
  },
  "agent_deck": {
    "executable": "/run/fixture/bin/agent-deck",
    "profile": "fixture-profile",
    "codex_executable": "/run/fixture/bin/codex",
    "work_directory": "/run/fixture/worktree",
    "start_timeout_seconds": 600,
    "wake_timeout_seconds": 600,
    "parent_policy": "NO_PARENT"
  },
  "ingress": {
    "executable": "/run/fixture/bin/agent-deck-signed-ingress",
    "socket": "/run/fixture/ingress/control.sock",
    "owner_host": "fixture-host",
    "owner_conductor": "0123abcd-1700000000",
    "provider": "github",
    "event": "pull_request",
    "object_alias": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "lifecycle": {
    "specialist_kind": "pr-warden",
    "repository_id": 1001,
    "pull_request_id": 3001,
    "pull_request_number": 7,
    "url": "https://fixture.invalid/repository/pull/7",
    "deadline": "2030-01-03T00:00:00Z",
    "next_check_at": "2030-01-01T00:00:00Z",
    "retention": "RETAIN",
    "rotation": {
      "context_measurement": "UNAVAILABLE",
      "owner_age_at": "2030-01-02T00:00:00Z",
      "health_failure_limit": 3
    }
  },
  "binding": {
    "head_repository_id": 1001,
    "head_ref": "refs/heads/fixture-branch",
    "worktree": "/run/fixture/worktree",
    "remote_name": "origin",
    "remote_url": "https://fixture.invalid/repository.git"
  },
  "provider": {
    "kind": "FAKE",
    "executable": "/run/fixture/bin/fake-current-facts",
    "fixture": "/run/fixture/provider.json",
    "timeout_seconds": 30
  },
  "local_git": {
    "kind": "FAKE",
    "executable": "/run/fixture/bin/fake-local-git",
    "fixture": "/run/fixture/local.json",
    "timeout_seconds": 30
  },
  "authority": {
    "read_only": true,
    "edit": false,
    "push": false,
    "comment": false,
    "reply": false,
    "resolve_thread": false,
    "bot_request": false,
    "body_rewrite": false,
    "merge": false,
    "close": false,
    "enqueue": false,
    "force_push": false,
    "branch_delete": false,
    "deploy": false,
    "takeover": false
  }
}
```

The two injected interfaces receive one strict request on standard input. `provider.kind` and
`local_git.kind` must both be exactly `FAKE`; any live kind fails before state creation. The test
provider returns either `OK` with the complete bounded current-fact object, `API_UNAVAILABLE`, a
malformed response, an identity mismatch, or a stale head. No provider identifier, object binding,
URL, worktree, session ID, result body, or secret is passed to those adapters in argv.

The public module accepts only `enable` and `runtimeConfig`. It is disabled by default. When enabled
it installs one hardened oneshot and five-minute timer, passes only the config path, permits only
Unix sockets, and reserves owner-only state/runtime directories. Before each tick, the service
materializes the public store source as `%t/agent-deck-pr-warden/controller.py` with mode `0700` and
executes that private runtime copy. Private enablement, a real object
binding, provider credentials, and any live read-only adapter require a later reviewed packet.

```nix
programs.agent-deck-pr-warden = {
  enable = true;
  runtimeConfig = "/run/fixture/pr-warden.json";
};
```

## Stop boundaries and proof limits

Stop `NEEDS_SCOPE` before a claim if canonical identity, owner/object binding, exact session
ownership, local branch provenance, a result, or sufficient ledger coverage is missing. Stop
`NEEDS_USER` for closed-unmerged disposition or if the target Agent Deck lacks launch/send
acceptance receipts, exact-ID show, or retained archive. Stop `NEEDS_FLEET` rather than extending
this source for new authentication, provider credentials/scopes, an ingress protocol or schema
change, migration, second queue/seen set/lease/owner database, multi-host writer, distributed
transaction, event coalescing, or public relay.

Offline verification uses synthetic executables and private temporary roots:

```sh
python3 -m unittest tests.test_agent_deck_pr_warden_controller
nix build --offline --no-link ./nix#checks.x86_64-linux.pr-warden
nix build --offline --no-link ./nix#packages.x86_64-linux.agent-deck-pr-warden
```

These checks prove deterministic local orchestration and fail-closed recovery only. They do not
prove live GitHub access, provider registration, public reachability, deployed credentials, an
enabled service, a real Agent Deck lifecycle, or any git/GitHub mutation.
