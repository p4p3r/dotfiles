# Bootstrapping a New Machine

This dotfiles repo uses **chezmoi** as an orchestrator that automatically:
1. Manages dotfiles (Fish, Git, Neovim, etc.)
2. Clones the private **dotfiles-private** repo
3. Integrates with **1Password** for secrets

Nix handles system configuration via `darwin-rebuild` (macOS) or `home-manager` (Linux).

## Quick Start

```bash
bash -c "$(curl -fsSL https://gist.githubusercontent.com/p4p3r/9724833647dd3217414f4463e5ca52bb/raw/bootstrap-new-machine.sh)"
```

Then, on macOS, in a new terminal:

```bash
chsh -s /run/current-system/sw/bin/fish
```

## Structure

```
~/Code/p4p3r/dotfiles/            # Chezmoi source directory (this repo)
├── .chezmoiexternal.toml         # Clones dotfiles-private to ~/.config/private
├── .chezmoiignore
├── nix/                          # Public Nix config (symlinked to ~/.config/nix)
│   ├── flake.nix                 # System configuration (darwin + home-manager)
│   ├── modules/
│   │   ├── common.nix            # Packages and home-manager config
│   │   ├── nix-settings.nix      # Nix daemon and performance settings
│   │   ├── darwin-homebrew.nix   # Homebrew casks and taps
│   │   ├── git-ssh.nix           # Git/SSH config (1Password integration)
│   │   └── shell/fish.nix        # Fish shell configuration
│   └── lib/
│       └── devtoolchain.nix      # Common dev tools
└── dot_config/fish/              # Fish functions and config (chezmoi-managed)

~/.config/private/                # Private config (git@github.com:p4p3r/dotfiles-private)
├── flake.nix                     # Exports homeManagerModule + darwinModule
├── nix/
│   ├── lib/mkOverlay.nix         # Shared overlay logic
│   └── modules/
│       ├── default.nix           # Private options (profiles, repoRoot)
│       ├── darwin.nix            # Private homebrew casks per profile
│       ├── shell/fish-private.nix
│       └── overlays/
│           ├── p4p3r.nix         # Personal repos
│           └── <profile>.nix      # Work overlay (files, repos, git identity)
└── overlay/<profile>/            # Files deployed to $HOME via home.file
```

## Daily Workflow

**Rebuild system after editing Nix config:**
```bash
nix_switch        # build + activate (includes private overlays)
```

**Other Nix helpers:**
```bash
nix_check         # validate flake
nix_build         # build without activating
nix_update        # update all flake inputs
nix_update nixpkgs  # update a single input
```

**Editing dotfiles:**
```bash
chezmoi edit ~/.config/fish/config.fish
chezmoi apply
```

**Syncing on another machine:**
```bash
chezmoi update    # pulls latest dotfiles + private repo
nix_switch        # rebuild system
```

## Agent Deck hook configuration probe

After chezmoi installs it, run `agent-deck-hook-probe` to inspect the effective Codex notification
and Claude hook configuration without invoking either runtime or any configured hook. Both runtimes
are required by default; `--optional-runtime codex` or `--optional-runtime claude` skips only a
runtime whose executable and configuration are both absent.

The probe verifies static configuration shape and executable reachability only. It does not prove
hook invocation, Agent Deck inbox delivery, child completion, or end-to-end Slack delivery. Inbox
signals remain advisory; poll immutable Agent Deck session IDs for authoritative completion.

## Agent Deck host-local work registry

`agent-deck-work-registry` is a small, single-writer companion for recording one immutable Agent
Deck owner session, requested/observed status, deadline, last poll time, and reason code per local
work item. It stores no prompts, messages, output, raw logs, paths, repository names, or arbitrary
metadata. The default registry is private host-local state at
`$XDG_STATE_HOME/agent-deck/work-registry.json` (falling back to
`~/.local/state/agent-deck/work-registry.json`); tests use an explicit temporary `--state`.

Registration, reconciliation, listing, and explicit terminal disposition are available through
`register`, `reconcile`, `list`/`show`, and `mark-terminal`. Reconciliation executes only
`agent-deck [-p PROFILE] session show <immutable-id> --json`; it does not query by title, consume
inbox hints, read child output, or control sessions. Polling proves the observed Agent Deck session
state, not work completion. Only a separate conductor verification can mark a work packet terminal.

The format has one version and no migration engine. Unknown or malformed state fails closed. The
registry uses a nonblocking local lock and atomic owner-only writes; concurrent writers,
distributed ownership, and cross-host state sharing are unsupported.

## Agent Deck maintenance collector

`agent-deck-maintenance-collector` is an hourly-capable, read-only inventory companion. It polls the
configured Agent Deck profile, explicitly configured git repositories, and filesystem capacity
bands. Its private host-local snapshot contains exact session IDs plus hashed references and bounded
reason codes—never raw paths, titles, commands, branches, prompts, messages, transcripts, or
provider bodies.

The first valid run records a silent baseline with a random fixed-format instance ID and generation
zero. Later identical observations preserve both; each candidate add/remove/reason change or
filesystem threshold-band transition increments the bounded generation once and emits exactly one
compact JSON event carrying the instance ID and exact old/new generations. A candidate requests
custodian inspection and never authorizes cleanup. The collector creates
no timer and performs no archive, stop, delete, prune, GitHub, Linear, Slack, or other network action.

Configure repositories with repeated `--repo PATH`; `/` is the default capacity target and repeated
`--filesystem PATH` overrides it. Snapshot state defaults to
`$XDG_STATE_HOME/agent-deck/maintenance-collector.json` (or
`~/.local/state/agent-deck/maintenance-collector.json`). `--fixture FILE` is the isolated strict-input
mode used by tests. Scheduling and report-only custodian behavior are separate, later packets.

## Report-only maintenance runtime

`agent-deck-maintenance-controller` is the single-writer hourly control tick around the collector.
Its first successful run records a baseline. Later unchanged and early ticks update only a bounded
checked timestamp and start no agent turn. A strict collector event (exit `10` or `30`) or one due,
durably unclaimed full-survey occurrence is claimed before the controller starts or wakes the one
report-only custodian.

The controller uses `agent-deck launch --json` only to create an unprompted custodian and obtain its
explicit immutable `session_id`, verified by an exact `session show ID --json`. It then submits the
trigger exactly once with `session send ID --acceptance-only --message-file -`—the same path used to
wake an existing owner—and records `SUBMITTED` only for the bounded, body-free receipt that binds
the exact owner, Codex session, and accepted turn generation. It never discovers an owner by title
or global-list diff. Launch success, status, pane state, process arguments, output bodies, legacy
delivery fields, malformed or mismatched receipts, interrupted claims, and indeterminate delivery
remain `NOT_VERIFIED`; none causes a retry or replacement launch.

Controller and collector state remain under the private local state directory. The controller file
contains only a schema version, host/profile aliases, the current collector instance, generation,
and fingerprint, stable trigger IDs and digests, bounded state and reason codes, UTC timestamps, an
exact verified or unverified session ID, optional
handoff/report references and digests, and a retention code. It never stores collector events,
prompts, paths, titles, commands, branches, output, transcripts, provider bodies, arbitrary
metadata, or secrets. Both files use owner-only modes, nonblocking single-writer locking, bounded
strict JSON, atomic replacement, and file plus directory `fsync`.

The generic Home Manager module is disabled by default and Linux-only. A host-specific layer may
enable it without changing this public source:

```nix
programs.agent-deck-maintenance = {
  enable = true;
  hostAlias = "build-host";
  profileAlias = "default";
  workDirectory = "/home/example";
  repositoryRoots = [ "/home/example/Code/project" ];
  filesystemRoots = [ "/" ];
  fullSurveyHours = 24;
};
```

The resulting user timer runs hourly with overlap prevention in the controller. Its hardened
oneshot has a private umask and state directory, explicit collector/Agent Deck/service timeouts,
and no environment-file or secret projection. To remain portable across unprivileged user managers
on hosts that restrict user namespaces, it intentionally omits `PrivateDevices`, `ProtectClock`,
`ProtectKernelLogs`, and `ProtectKernelModules`; systemd implements each by narrowing the capability
bounding set. The remaining process hardening stays enabled, while namespace protections remain
best-effort according to host support. Enabling the module installs the exact controller, collector,
and [report-only custodian charter](docs/agent-deck-fleet-custodian-charter.md) used by the unit.
Nothing in this module activates cleanup: archive, delete, prune, stop, restart, cache reclamation,
branch/worktree mutation, external writes, merge, and deploy remain forbidden.

## Architecture

- **chezmoi** manages dotfiles and clones the private repo via `.chezmoiexternal.toml`
- **Nix flake** (`~/.config/nix`) defines the full system: packages, shell, git, SSH
- **Private flake** (`~/.config/private`) is a flake input providing overlay modules
- **Profiles** (`private.profiles`) control which overlays are active per host
- **1Password** provides SSH keys and secrets (no secrets in either repo)
