# Conductor metadata tick

`agent-deck-conductor-tick` is a bounded caller of the existing work registry.
It polls session metadata, preserves each observation independently, and never
wakes an agent or infers work completion. It uses no provider, transcript,
output, inbox, pane, or Agent Deck discovery interface.

```sh
agent-deck-conductor-tick --state /private/control/registry.json --profile example
```

The state path is explicit. Its parent must be owner-only; the registry enforces
its existing file modes and nonblocking single-writer lock. All registration,
reconciliation, and terminal decisions must use that registry CLI. The timer is
the conductor's sole automatic caller, not another work owner. Do not configure
two timers for the same file or copy it between hosts.

Each tick reads the sanitized registry listing and selects at most twelve
nonterminal records, oldest `last_checked_at` first, then work ID. Never-checked
records lead. Each selected reconciliation commits before the next begins.
Agent Deck receives only `[-p PROFILE] session show IMMUTABLE_ID --json` from the
registry. A returned ID mismatch, missing session, unknown state, or timeout
preserves the registered owner and produces a bounded unknown observation.

Defaults are five seconds per poll and an 80-second caller budget. The caller
reserves two seconds for registry commit/cleanup; budget exhaustion retains
earlier observations and leaves remaining records for a later tick. It may
terminate only its own timed-out registry invocation and CLI descendants.
Registry schema and terminal handling are unchanged.

Output contains a fixed code, completed nonterminal reconciliation count,
remaining records from the initial snapshot, and bounded events. `CHANGED`
means an observation changed; `UNKNOWN` means a new unverified observation;
`OVERDUE` means the deadline passed since the prior check. Repeated observations
produce no event. Exit 0 covers the selected checks only; exit 4 means an
unverified check, caller/registry failure, or exhausted time budget. Neither is
evidence that work completed. Waiting/idle still requires independent acceptance
and an explicit conductor `mark-terminal` decision.

The Home Manager module is disabled by default. Configure only its declared
profile/conductor; applying an enabled configuration creates a timer, so source
and offline tests are not activation authority.

```nix
programs.agent-deck-control = {
  enable = true;
  profileName = "example";
  conductorName = "controller";
};
```

The generated oneshot has a 90-second limit, no service restart policy, private
state, and a two-minute cadence. Its default registry is
`$XDG_STATE_HOME/agent-deck-control/PROFILE/CONDUCTOR.json`; the same path must be
used for registration and terminal decisions. Set `registryState` explicitly
when adopting an existing registry; no migration is performed.

Offline acceptance uses private roots and a fixture Agent Deck executable:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_agent_deck_conductor_tick.py'
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_agent_deck_work_registry.py'
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_agent_deck_control_nix.py'
```

Installation, scheduler activation, live child reconciliation, and independent
completion/reporting remain separate canaries. Disagreement about ownership or
what an observation proves should be resolved before activation.
