# QMK compilers: add ARM and AVR GCC directories to PATH and update LDFLAGS.
for ARM_GCC_BIN in (find /opt/homebrew/opt/arm-gcc-bin* -maxdepth 1 -type d)
    set -x LDFLAGS "-L$ARM_GCC_BIN/lib $LDFLAGS"
    set -x PATH $ARM_GCC_BIN/bin $PATH
end

for AVR_GCC in (find /opt/homebrew/opt/avr-gcc* -maxdepth 1 -type d)
    set -x LDFLAGS "-L$AVR_GCC/lib $LDFLAGS"
    set -x PATH $AVR_GCC/bin $PATH
end

