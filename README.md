# 🚀 Bootstrapping a New Machine

This repo + [dotfiles-private](https://github.com/p4p3r/dotfiles-private) can fully set up a new macOS or Linux laptop using **Nix** + **chezmoi**, with secrets from **1Password**.

## Quick start

Run this one-liner:

```bash
bash -c "$(curl -fsSL https://gist.githubusercontent.com/p4p3r/9724833647dd3217414f4463e5ca52bb/raw/c968210f793615d35f2b541138b9dc881436dfb5/bootstrap-new-machine.sh)"
```

Then, if on MacOS, in a new terminal:

```bash
chsh -s /run/current-system/sw/bin/fish
```
