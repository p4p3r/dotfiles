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

## Conductor (tmux, separate socket)

Runs in its own Ghostty window via `conductor` command. Uses a dedicated tmux server (socket: `conductor`) with Zellij-mirrored keybinds. Rose Pine Dawn theme.

### Prefix: Ctrl+Space

Status bar shows hint bar with available keys for each mode.

### Prefix Keys (Ctrl+Space → key)
| Key | Action |
|-----|--------|
| t | Enter tab mode |
| p | Enter pane mode |
| n | Enter resize mode |
| s | Scroll/copy mode |
| c | New window |
| d | Detach |
| q | Kill session |
| z | Zoom pane (fullscreen toggle) |
| f | Float pane (floax) |
| F | Float menu |
| w | Add random worktree + claude window |
| h/j/k/l | Focus pane left/down/up/right |
| 1-9 | Go to window by number |
| , | Rename window |
| x | Kill pane |
| o | Next pane |
| [ | Copy mode |
| " | Split vertical |
| % | Split horizontal |

### Tab Mode (prefix → t → key)
| Key | Action |
|-----|--------|
| h/l | Previous/next tab |
| j/k | Next/previous tab |
| 1-9 | Go to tab by number |
| n | New tab |
| r | Rename tab |
| x | Kill tab |

### Pane Mode (prefix → p → key)
| Key | Action |
|-----|--------|
| h/j/k/l | Focus pane |
| n/r | Split horizontal |
| d | Split vertical |
| x | Kill pane |
| z | Zoom (fullscreen) |
| p | Next pane |

### Resize Mode (prefix → n → key)
| Key | Action |
|-----|--------|
| h/j/k/l | Resize 5 cells |
| H/J/K/L | Resize 1 cell |

### Copy Mode
| Key | Action |
|-----|--------|
| q | Quit |
| Space | Start selection |
| / | Search |

---

## Fish Shell Functions

### Claude Code
| Command | Description |
|---------|-------------|
| `claude [args]` | Launch Claude Code with API key unset + sleep prevention |
| `claude-worktree <branch> [base]` | Create/open git worktree in new Ghostty window + auto-start claude |

### Conductor
| Command | Description |
|---------|-------------|
| `conductor` | Open conductor view for current repo (Ghostty + tmux + lazygit) |
| `conductor-add <branch>` | Add worktree + claude/terminal window to running conductor |
| `conductor-add-random` | Same as above with random 3-word branch name |

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
5. Auto-launch `claude` in the new session

## Workflow: Conductor

```
conductor
```

From any git repo, opens a Ghostty window with tmux:
- **Window 1 (Overview)**: lazygit showing repo status + diffs
- **Window 2..N**: One per existing worktree, with claude (left 60%) + shell (right 40%)

Add worktrees on the fly:
- `conductor-add feat-name` — named branch
- `conductor-add-random` or `Ctrl+Space → w` — random 3-word branch

### Session Naming Convention

| Context | Session Name |
|---------|-------------|
| Home directory | `main` |
| `~/.config` | `config` |
| Git repo | repo basename (e.g., `my-project`) |
| Git worktree | abbreviated repo + branch (e.g., `sethmo~feature-x`) |
| Conductor | `c-<reponame>` (e.g., `c-my-project`) |
| Long names (>40 chars) | auto-abbreviated (2 chars per word part) |
