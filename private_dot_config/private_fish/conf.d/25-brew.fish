# If brew exists, add its directories and GNU utils to PATH
if type -q /opt/homebrew/bin/brew
    # Load Homebrew environment
    eval (/opt/homebrew/bin/brew shellenv)

    # Set BREW_PREFIX from brew
    set -l BREW_PREFIX (brew --prefix)
    
    if test -d "$BREW_PREFIX/bin"
        set -x PATH $PATH $BREW_PREFIX/bin
    end
    if test -d "$BREW_PREFIX/sbin"
        set -x PATH $PATH $BREW_PREFIX/sbin
    end
    
    # Add any gnubin directories from Homebrew-installed packages
    for d in $BREW_PREFIX/opt/*/libexec/gnubin
        if test -d "$d"
            set -x PATH $d $PATH
        end
    end
    
    # Additional GNU utilities
    set -x PATH /opt/homebrew/opt/gnu-getopt/bin $PATH
    set -x PATH /opt/homebrew/opt/ssh-copy-id/bin $PATH

    # Supplementary include and lib paths from brew
    set -x CPATH $CPATH $BREW_PREFIX/include
    set -x LIBRARY_PATH $LIBRARY_PATH $BREW_PREFIX/lib
end

