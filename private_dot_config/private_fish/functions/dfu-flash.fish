function dfu-flash
    # Check that the firmware file argument exists.
    if not test -f $argv[1]
        echo "Usage: dfu-flash <firmware.hex> [left|right]"
        return 1
    end

    # Wait for the bootloader.
    while true
        set -l out (ioreg -p IOUSB | grep ATm32U4DFU)
        if test -n "$out"
            break
        end
        echo "Waiting for ATm32U4DFU bootloader..."
        sleep 3
    end

    dfu-programmer atmega32u4 erase --force

    if test "$argv[2]" = "left"
        echo "\nFlashing left EEPROM"
        echo ':0F000000000000000000000000000000000001F0\n:00000001FF' | dfu-programmer atmega32u4 flash --force --suppress-validation --eeprom STDIN
    else if test "$argv[2]" = "right"
        echo "\nFlashing right EEPROM"
        echo ':0F000000000000000000000000000000000000F1\n:00000001FF' | dfu-programmer atmega32u4 flash --force --suppress-validation --eeprom STDIN
    end

    echo "\nFlashing $argv[1]"
    dfu-programmer atmega32u4 flash --force $argv[1]
    dfu-programmer atmega32u4 reset
end
