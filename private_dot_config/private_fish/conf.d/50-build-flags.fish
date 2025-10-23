# Set prefixes for zlib and openssl
set -x ZLIB_PREFIX /opt/homebrew/opt/zlib
set -x OPENSSL_PREFIX /opt/homebrew/opt/openssl

# Compiler and linker flags
set -x LDFLAGS "-L$ZLIB_PREFIX/lib -L$OPENSSL_PREFIX/lib"
set -x CPPFLAGS "-I$ZLIB_PREFIX/include -I$OPENSSL_PREFIX/include"
set -x CFLAGS "-I$ZLIB_PREFIX/include -I$OPENSSL_PREFIX/include"

set -x PKG_CONFIG_PATH /usr/local/lib/pkgconfig $PKG_CONFIG_PATH
# Prepend zlib’s pkgconfig directory to PKG_CONFIG_PATH
set -x PKG_CONFIG_PATH $ZLIB_PREFIX/lib/pkgconfig $PKG_CONFIG_PATH

# Other build-related variables
set -x FLAGS_GETOPT_CMD /opt/homebrew/opt/gnu-getopt/bin/getopt
set -x PIPENV_VENV_IN_PROJECT true

