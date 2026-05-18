# Disable terminal flow control (ixon).
#
# By default the tty driver intercepts Ctrl+S as XOFF (pause output) and
# Ctrl+Q as XON (resume output). Two consequences:
#  - Ctrl+S in editors / TUIs (e.g. agent-deck's "detach") is swallowed
#    before reaching the app, looking like nothing happened.
#  - Ctrl+Q likewise — agent-deck reserves Ctrl+Q for "detach (keep tmux
#    running)" but the tty eats it.
#
# Disable flow control so those keystrokes reach the running app.
# Interactive-only; non-interactive shells don't have a tty to configure.
if status is-interactive
    stty -ixon 2>/dev/null
end
