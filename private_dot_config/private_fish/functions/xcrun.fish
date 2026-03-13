function xcrun --wraps xcrun -d "Use system xcrun to avoid Nix xcbuild warnings"
    /usr/bin/xcrun $argv
end
