# Shortcuts & DevEx Reference

## AeroSpace (Window Manager)

Modifier: **Alt**

### Layout
| Shortcut | Action |
|----------|--------|
| Alt+A | Horizontal tiles |
| Alt+S | Vertical tiles |
| Alt+D | Fullscreen |
| Alt+F | Horizontal accordion |
| Alt+. | Cycle layouts (h_tiles, v_tiles, h_accordion, v_accordion) |
| Alt+/ | Cycle layouts (v_tiles, h_tiles, v_accordion, h_accordion) |
| Alt+T | Toggle floating/tiling |
| Alt+Z | Flatten + balance sizes |
| Alt+Shift+Z | Reload config |

### Focus & Navigation
| Shortcut | Action |
|----------|--------|
| Alt+H | Focus previous (DFS) |
| Alt+L | Focus next (DFS) |
| Alt+Y | Focus first window |
| Alt+J | Previous workspace |
| Alt+K | Next workspace |
| Alt+1/2/3 | Go to workspace 1/2/3 |
| Ctrl+Alt+X/C/V | Go to workspace 1/2/3 (alternate) |

### Window Management
| Shortcut | Action |
|----------|--------|
| Alt+Enter | Swap with left (promote) |
| Alt+N | Shrink main (-50) |
| Alt+M | Grow main (+50) |
| Alt+U | Join with left |
| Alt+O | Join with right |
| Alt+Shift+J | Swap DFS previous |
| Alt+Shift+K | Swap DFS next |
| Alt+Shift+H | Move window to previous workspace |
| Alt+Shift+L | Move window to next workspace |
| Alt+Shift+X/C/V | Move window to workspace 1/2/3 |

### Scripts
| Shortcut | Action |
|----------|--------|
| Alt+G | Toggle main/stack layout |
| Alt+Shift+B | Collapse all to workspace 1 (laptop mode) |
| Alt+Shift+N | Redistribute across workspaces (home layout) |

---

## Zellij (Terminal Multiplexer)

### Prefix: Ctrl+Space (or Ctrl+B)

Press the prefix, then the key below.

### Mode Switchers (from tmux mode)
| Key | Enters Mode |
|-----|-------------|
| t | Tab |
| p | Pane |
| s | Scroll |
| n | Resize |
| h | Move |
| g | Locked |
| Esc | Back to normal |

### Direct Shortcuts (normal mode, no prefix needed)
| Shortcut | Action |
|----------|--------|
| Cmd+H/J/K/L | Move focus left/down/up/right |
| Cmd+Left/Right | Move focus or tab left/right |
| Cmd+N | New pane |
| Cmd+F | Toggle floating panes |
| Cmd+I/O | Move tab left/right |
| Cmd+[/] | Previous/next swap layout |

### Tab Mode (prefix + t)
| Key | Action |
|-----|--------|
| h/l | Previous/next tab |
| j/k | Next/previous tab |
| 1-9 | Go to tab by number |
| n | New tab |
| r | Rename tab |
| x | Close tab |
| Tab | Toggle last tab |
| [/] | Break pane left/right |

### Pane Mode (prefix + p)
| Key | Action |
|-----|--------|
| h/j/k/l | Move focus |
| n | New pane |
| d | New pane down |
| r | New pane right |
| x | Close pane |
| f | Fullscreen |
| w | Toggle floating |
| e | Toggle embed/float |
| z | Toggle pane frames |
| c | Rename pane |

### Resize Mode (prefix + n)
| Key | Action |
|-----|--------|
| h/j/k/l | Grow left/down/up/right |
| H/J/K/L | Shrink left/down/up/right |
| +/- | Grow/shrink overall |

### Scroll Mode (prefix + s or prefix + [)
| Key | Action |
|-----|--------|
| j/k | Scroll down/up |
| d/u | Half page down/up |
| Ctrl+F/Ctrl+B | Page down/up |
| s | Enter search |
| e | Edit scrollback in $EDITOR |

### Session
| Shortcut | Action |
|----------|--------|
| prefix + d | Detach |
| prefix + q | Quit |
| Ctrl+G | Exit locked mode |

---

## Fish Shell Functions

### Claude Code
| Command | Description |
|---------|-------------|
| `cclaude [args]` | Launch Claude Code with sleep prevention |
| `claude-squad [args]` | Launch Claude Code with Agent Teams + sleep prevention |
| `claude-worktree <branch> [base]` | Create/open git worktree in new Ghostty window + auto-start cclaude |

### Terminal & Sessions
| Command | Description |
|---------|-------------|
| `ghostty-here [dir]` | Open new Ghostty window in directory (default: current) |
| `zj-list` | List all Zellij sessions |

### Nix System Management
| Command | Description |
|---------|-------------|
| `nix_build` | Build darwin system configuration (dry run) |
| `nix_check` | Run flake validation checks |
| `nix_switch` | Build and activate system configuration |
| `nix_update [inputs]` | Update flake inputs (all or specific) |

### Sleep Prevention
| Command | Description |
|---------|-------------|
| `caffeinate-start` | Start preventing macOS sleep |
| `caffeinate-stop` | Stop all sleep prevention |
| `caffeinate-status` | Check if caffeinate is active |

---

## Workflow: Claude Worktree

```
claude-worktree claudio/harness develop
```

This will:
1. Create a git worktree at `../repo-claudio-harness` (branch `claudio/harness`)
2. Symlink `.envrc` from the parent repo (if exists) + `direnv allow`
3. Open a new Ghostty window in the worktree directory
4. Auto-start Zellij with session name like `sethmo~claudio-harness`
5. Auto-launch `cclaude` in the new session

### Session Naming Convention

| Context | Session Name |
|---------|-------------|
| Home directory | `main` |
| `~/.config` | `config` |
| Git repo | repo basename (e.g., `my-project`) |
| Git worktree | abbreviated repo + branch (e.g., `sethmo~feature-x`) |
| Long names (>40 chars) | auto-abbreviated (2 chars per word part) |
