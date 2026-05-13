# Build flags for native compilation against Homebrew-provided zlib / openssl /
# gnu-getopt. macOS-only — on Linux these libs come from the system package
# manager or Nix and projects can pick them up via pkg-config without any of
# this scaffolding.
if test (uname) != Darwin
    set -x PIPENV_VENV_IN_PROJECT true
    exit 0
end

# Resolve prefixes only if the formulae are actually installed; fall back to
# leaving the vars unset rather than pointing at non-existent paths.
if test -d /opt/homebrew/opt/zlib
    set -x ZLIB_PREFIX /opt/homebrew/opt/zlib
end
if test -d /opt/homebrew/opt/openssl
    set -x OPENSSL_PREFIX /opt/homebrew/opt/openssl
end

if set -q ZLIB_PREFIX; and set -q OPENSSL_PREFIX
    set -x LDFLAGS "-L$ZLIB_PREFIX/lib -L$OPENSSL_PREFIX/lib"
    set -x CPPFLAGS "-I$ZLIB_PREFIX/include -I$OPENSSL_PREFIX/include"
    set -x CFLAGS "-I$ZLIB_PREFIX/include -I$OPENSSL_PREFIX/include"
end

set -x PKG_CONFIG_PATH /usr/local/lib/pkgconfig $PKG_CONFIG_PATH
if set -q ZLIB_PREFIX
    set -x PKG_CONFIG_PATH $ZLIB_PREFIX/lib/pkgconfig $PKG_CONFIG_PATH
end

if test -x /opt/homebrew/opt/gnu-getopt/bin/getopt
    set -x FLAGS_GETOPT_CMD /opt/homebrew/opt/gnu-getopt/bin/getopt
end

set -x PIPENV_VENV_IN_PROJECT true
