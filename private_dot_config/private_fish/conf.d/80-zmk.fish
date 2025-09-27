# ZMK environment settings
set -x ZEPHYR_TOOLCHAIN_VARIANT gnuarmemb
set -x GNUARMEMB_TOOLCHAIN_PATH /Applications/ArmGNUToolchain/11.3.rel1/arm-none-eabi

# If you have a fish-compatible version of the zephyr env script, source it.
if test -f $HOME/src/p4p3r/zmk/zephyr/zephyr-env.fish
    source $HOME/src/p4p3r/zmk/zephyr/zephyr-env.fish
else
    # Alternatively, you might run the sh version in a subshell:
    # sh $HOME/src/p4p3r/zmk/zephyr/zephyr-env.sh
end

