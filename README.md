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

The first valid run records a silent baseline. Later identical observations stay silent; a candidate
add/remove/reason change or filesystem threshold-band transition emits exactly one compact JSON
event. A candidate requests custodian inspection and never authorizes cleanup. The collector creates
no timer and performs no archive, stop, delete, prune, GitHub, Linear, Slack, or other network action.

Configure repositories with repeated `--repo PATH`; `/` is the default capacity target and repeated
`--filesystem PATH` overrides it. Snapshot state defaults to
`$XDG_STATE_HOME/agent-deck/maintenance-collector.json` (or
`~/.local/state/agent-deck/maintenance-collector.json`). `--fixture FILE` is the isolated strict-input
mode used by tests. Scheduling and report-only custodian behavior are separate, later packets.

## Architecture

- **chezmoi** manages dotfiles and clones the private repo via `.chezmoiexternal.toml`
- **Nix flake** (`~/.config/nix`) defines the full system: packages, shell, git, SSH
- **Private flake** (`~/.config/private`) is a flake input providing overlay modules
- **Profiles** (`private.profiles`) control which overlays are active per host
- **1Password** provides SSH keys and secrets (no secrets in either repo)
