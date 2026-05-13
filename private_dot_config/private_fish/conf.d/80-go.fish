# Go: keep modules under $HOME/.golang, add GOPATH/bin to PATH.
# GOROOT only points at the Homebrew install on macOS — on Linux, Go's
# installer / nixpkgs / your distro put GOROOT in the binary's own prefix
# and we don't need to set it. Leave it unset there so `go` figures it out.
set -x GOPATH $HOME/.golang
if test (uname) = Darwin; and test -d /opt/homebrew/opt/golang/libexec
    set -x GOROOT /opt/homebrew/opt/golang/libexec
end

set -x PATH $PATH $GOPATH/bin
if set -q GOROOT
    set -x PATH $PATH $GOROOT/bin
end
