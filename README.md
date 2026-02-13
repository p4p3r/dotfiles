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
│           └── semgrep.nix       # Work overlay (files, repos, git identity)
└── overlay/semgrep/              # Files deployed to $HOME via home.file
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

## Architecture

- **chezmoi** manages dotfiles and clones the private repo via `.chezmoiexternal.toml`
- **Nix flake** (`~/.config/nix`) defines the full system: packages, shell, git, SSH
- **Private flake** (`~/.config/private`) is a flake input providing overlay modules
- **Profiles** (`private.profiles`) control which overlays are active per host
- **1Password** provides SSH keys and secrets (no secrets in either repo)
