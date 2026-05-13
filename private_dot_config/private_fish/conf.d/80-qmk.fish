# QMK compilers (macOS only — paths live under /opt/homebrew). Skip on Linux
# so the find globs don't fail with "Unmatched wildcard" on fish startup.
if test (uname) != Darwin
    exit 0
end

# Toolchains are only present if you've `brew install`'d them. Guard the
# globs so a fresh Mac without QMK installed doesn't trip on the wildcards.
for ARM_GCC_BIN in /opt/homebrew/opt/arm-gcc-bin*
    test -d $ARM_GCC_BIN; or continue
    for d in (find $ARM_GCC_BIN -maxdepth 1 -type d)
        set -x LDFLAGS "-L$d/lib $LDFLAGS"
        set -x PATH $d/bin $PATH
    end
end

for AVR_GCC in /opt/homebrew/opt/avr-gcc*
    test -d $AVR_GCC; or continue
    for d in (find $AVR_GCC -maxdepth 1 -type d)
        set -x LDFLAGS "-L$d/lib $LDFLAGS"
        set -x PATH $d/bin $PATH
    end
end
