# Agent Deck Slack gateway watchdog

This disabled-by-default Home Manager companion qualifies a direct Slack
gateway through an owner-only Unix control socket. A running systemd unit is
not health evidence. The watchdog neither reads Slack messages nor inspects an
Agent Deck transcript.

## Required control protocol

The server socket must be owned by the invoking uid with mode `0600`. On Linux,
the peer uid must also match through `SO_PEERCRED`. One connection performs
three bounded newline-delimited JSON steps:

1. Client sends `{"version":1,"type":"hello","nonce":"<32 lower hex>"}`.
2. Server returns one strict `pong` object, echoing the nonce.
3. Client sends the matching `close`; the server returns the matching `closed`.

The `pong` object has exactly this body-free schema:

```json
{
  "version": 1,
  "type": "pong",
  "nonce": "<echoed nonce>",
  "identity": {
    "binary_sha256": "<64 lower hex>",
    "config_sha256": "<64 lower hex>",
    "row_binding_alias": "<16-128 URL-safe opaque characters>"
  },
  "runner": {
    "state": "running",
    "exit_code": null,
    "terminal": false,
    "degraded": false
  },
  "pump": {
    "state": "fresh",
    "last_progress_age_seconds": 3
  },
  "backlog": {
    "state": "pending",
    "oldest_age_seconds": 8
  },
  "egress": {
    "state": "clear"
  },
  "conductor": {
    "state": "working",
    "turn_age_seconds": 7200
  }
}
```

Allowed runner states are `running` and `exited`. An exited runner carries an
integer exit code; a running runner carries `null`. Pump states are `idle`,
`fresh`, `stale`, `stalled`, and `unknown`; backlog states are `empty`,
`pending`, and `unknown`; egress states are `clear`, `uncertain`, and `unknown`;
conductor states are `idle`, `working`, and `unknown`. Age fields are present
only where the schema requires them. Frames are at most 16 KiB, strict UTF-8,
and reject missing or unknown fields.

The separate conductor state is intentional. A long `working` turn, even one
in the oldest reported age band, is not a stuck gateway when the control
round-trip completes and the pump is fresh. A control timeout is instead a
stuck status call and fails closed without recovery.

## Recovery boundary

Only a complete, identity-matching handshake that reports an already-exited,
nonterminal, nondegraded runner with exit code `75`, known backlog/conductor
state, and clear egress can request recovery. The watchdog durably consumes one
restart token before calling `systemctl --user restart`. The token is keyed by
the pinned binary digest, config digest, and row-binding alias; it survives
watchdog and gateway restarts. A timeout or failed restart still consumes it.

Exit `78`, terminal or degraded state, stale/stalled/unknown pump, unknown
state, uncertain egress, missing or mismatched identity, unsafe socket, and any
status timeout never restart. The oneshot watchdog service has no `Restart=`
policy, so no `RestartSec` loop exists.

The watchdog prints one compact body-free result. Exact identities are never
printed; ages are reduced to fixed bands. Its state contains only a derived
incarnation digest, the one-shot retry bit, and its timestamp.

## Settings and Home Manager

The module requires an owner-only (`0600`) runtime JSON file outside the Nix
store:

```json
{
  "version": 1,
  "control_socket": "/run/user/1000/agent-deck/slack-v2-control.sock",
  "gateway_unit": "agent-deck-conductor-slack-v2.service",
  "expected_incarnation": {
    "binary_sha256": "<64 lower hex>",
    "config_sha256": "<64 lower hex>",
    "row_binding_alias": "row_binding_alias_fixture"
  },
  "timeouts": {
    "connect_ms": 500,
    "io_ms": 500,
    "restart_ms": 10000
  }
}
```

Enable it only after the exact gateway candidate implements and qualifies the
protocol:

```nix
programs.agent-deck-slack-watchdog = {
  enable = true;
  settingsFile = "/home/example/.config/agent-deck/slack-watchdog.json";
};
```

This source module installs no settings, enables nothing by default, and has no
provider credentials or network calls. The current Agent Deck Slack candidate
does not yet expose this control socket, so live interface, restart, and
end-to-end Slack proof remain `NOT_VERIFIED` until that separate gateway work
and a controlled canary are complete.
