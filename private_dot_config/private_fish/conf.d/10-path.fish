# Base PATH and pkg-config
# Note: fish’s PATH is a list of directories.
set -x PATH /usr/local/bin /usr/local/sbin /sbin /usr/sbin /bin /usr/bin $PATH

# Add local bin directory
set -x PATH $HOME/.local/bin $PATH
