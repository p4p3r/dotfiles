# Set GPG_TTY if gpg is available
if type -q gpg
    set -x GPG_TTY (tty)
end
