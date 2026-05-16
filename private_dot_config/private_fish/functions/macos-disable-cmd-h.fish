function macos-disable-cmd-h -d "Disable macOS Cmd+H hide shortcut for Ghostty"
    echo "Disabling Cmd+H (hide window) for Ghostty..."

    # This tells macOS to not use Cmd+H for hiding Ghostty windows
    defaults write com.mitchellh.ghostty NSUserKeyEquivalents -dict-add "Hide Ghostty" nil

    echo "✅ Done! Cmd+H is now disabled for Ghostty"
    echo "⚠️  You may need to restart Ghostty for this to take effect"
    echo ""
    echo "To re-enable later, run:"
    echo "  defaults delete com.mitchellh.ghostty NSUserKeyEquivalents"
end
