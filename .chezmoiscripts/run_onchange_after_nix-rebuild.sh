#!/bin/bash
# This script runs whenever the Nix configuration changes
# It automatically rebuilds the system with the new configuration

set -e

echo "Checking if Nix configuration has changed..."

# Only run on macOS (for darwin-rebuild)
if [[ "$(uname)" != "Darwin" ]]; then
    echo "Not on macOS, skipping darwin-rebuild"
    echo "Run 'home-manager switch --flake ~/.config/nix' manually on Linux"
    exit 0
fi

# Check if nix config symlink/directory exists
if [[ ! -e "$HOME/.config/nix" ]]; then
    echo "~/.config/nix not found, skipping rebuild"
    echo "Run 'chezmoi apply' first to create the symlink"
    exit 0
fi

echo "Nix configuration found, rebuilding system..."
echo ""

# Rebuild the system
sudo darwin-rebuild switch --flake "$HOME/.config/nix"

echo ""
echo "System rebuild complete!"
