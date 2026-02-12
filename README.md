# 🚀 Bootstrapping a New Machine

This dotfiles repo uses **chezmoi** as an orchestrator that automatically:
1. Clones public **nix-config** and private **nix-config-private** repos
2. Runs `darwin-rebuild` (macOS) or `home-manager` (Linux)
3. Manages other dotfiles (Fish, etc.)
4. Integrates with **1Password** for secrets

## Quick Start

Run this one-liner:

```bash
bash -c "$(curl -fsSL https://gist.githubusercontent.com/p4p3r/9724833647dd3217414f4463e5ca52bb/raw/c968210f793615d35f2b541138b9dc881436dfb5/bootstrap-new-machine.sh)"
```

Then, if on macOS, in a new terminal:

```bash
chsh -s /run/current-system/sw/bin/fish
```

## How It Works

### Chezmoi as Orchestrator

```
~/.local/share/chezmoi/           # Chezmoi source directory (this repo)
├── .chezmoiexternal.toml         # Clones nix-config and nix-config-private
├── .chezmoiscripts/
│   └── run_onchange_after_nix-rebuild.sh  # Auto-runs darwin-rebuild
└── .chezmoiignore                # Ignores .config/nix/** (managed externally)
```

**On `chezmoi apply`:**
1. Clones `~/.config/nix` from GitHub (public repo)
2. Clones `~/.config/nix-private` from GitHub (private repo)
3. Runs `darwin-rebuild switch` automatically
4. Applies other dotfiles (Fish config, etc.)

### Nix Configuration Structure

```
~/.config/nix/              # Public Nix config (https://github.com/p4p3r/nix-config)
├── flake.nix               # Main system configuration
├── modules/
│   ├── common.nix          # Home Manager packages
│   ├── nix-settings.nix    # Performance settings
│   └── git-ssh.nix         # Git/SSH config (1Password integration)
└── lib/
    └── base-devtools.nix   # Common dev tools

~/.config/nix-private/      # Private Nix config (git@github.com:p4p3r/nix-config-private.git)
├── flake.nix               # Exports modules to main config
├── modules/
│   ├── work-projects.nix   # Symlinks .envrc to work projects
│   └── shell/
│       └── fish-private.nix  # Private Fish functions
└── projects/
    ├── work-project-a/     # Private devenv configs
    │   ├── devenv.nix
    │   ├── flake.nix
    │   └── .envrc
    └── work-project-b/
        ├── devenv.nix
        ├── flake.nix
        └── .envrc
```

### Daily Workflow

**Making changes to Nix config:**
```bash
cd ~/.config/nix
# Edit files...
git add -A && git commit -m "Update config" && git push
```

**Making changes to dotfiles:**
```bash
chezmoi edit ~/.config/fish/config.fish
chezmoi apply
```

**Updating on another machine:**
```bash
chezmoi update  # Pulls latest dotfiles + nix configs
# darwin-rebuild runs automatically via chezmoi script
```

## Architecture Benefits

✅ **Single command restore** - `chezmoi apply` sets up everything  
✅ **Public/private split** - Sensitive project names stay private  
✅ **Git-native** - Nix configs are proper Git repos with history  
✅ **Modular** - Each component (chezmoi, nix-config, nix-private) is independent  
✅ **1Password integration** - SSH keys and secrets managed securely
