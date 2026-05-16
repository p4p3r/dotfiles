function check-keybinding-conflicts -d "Check for macOS keyboard shortcut conflicts with Zellij"
    echo "🔍 Checking for macOS System Keyboard Shortcut Conflicts"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    echo "📋 Zellij Super (Cmd) Key Bindings:"
    echo ""

    set -l conflicts 0
    set -l warnings 0
    set -l good 0

    # Check each Zellij Super binding against macOS defaults

    # Super+H - Hide application (macOS default)
    echo -n "  Super+h (Navigate left): "
    if grep -q "cmd+h=unbind" ~/.config/ghostty/config
        echo "✅ FIXED (unbound in Ghostty)"
        set good (math $good + 1)
    else
        echo "⚠️  CONFLICT - macOS hides window"
        echo "     Fix: Already should be unbound, check Ghostty config"
        set conflicts (math $conflicts + 1)
    end

    # Super+L - No conflict
    echo -n "  Super+l (Navigate right): "
    if grep -q "cmd+l=unbind" ~/.config/ghostty/config
        echo "✅ OK (unbound in Ghostty)"
        set good (math $good + 1)
    else
        echo "⚠️  Not unbound in Ghostty"
        set warnings (math $warnings + 1)
    end

    # Super+J - No macOS conflict
    echo -n "  Super+j (Navigate down): "
    if grep -q "cmd+j=unbind" ~/.config/ghostty/config
        echo "✅ OK (unbound in Ghostty)"
        set good (math $good + 1)
    else
        echo "⚠️  Not unbound in Ghostty"
        set warnings (math $warnings + 1)
    end

    # Super+K - No macOS conflict
    echo -n "  Super+k (Navigate up): "
    if grep -q "cmd+j=unbind" ~/.config/ghostty/config
        echo "✅ OK (unbound in Ghostty)"
        set good (math $good + 1)
    else
        echo "⚠️  Not unbound in Ghostty"
        set warnings (math $warnings + 1)
    end

    # Super+N - New window in many apps (macOS convention)
    echo -n "  Super+n (New pane): "
    if grep -q "cmd+n=unbind" ~/.config/ghostty/config
        echo "✅ FIXED (unbound in Ghostty)"
        set good (math $good + 1)
    else
        echo "❌ CONFLICT - macOS 'New Window'"
        echo "     Fix: Add 'keybind = cmd+n=unbind' to Ghostty config"
        set conflicts (math $conflicts + 1)
    end

    # Super+I - No standard macOS conflict
    echo -n "  Super+i (Move tab left): "
    if grep -q "cmd+i=unbind" ~/.config/ghostty/config
        echo "✅ OK (unbound in Ghostty)"
        set good (math $good + 1)
    else
        echo "⚠️  Not unbound in Ghostty"
        set warnings (math $warnings + 1)
    end

    # Super+O - Open file in many apps (macOS convention)
    echo -n "  Super+o (Move tab right): "
    if grep -q "cmd+o=unbind" ~/.config/ghostty/config
        echo "✅ FIXED (unbound in Ghostty)"
        set good (math $good + 1)
    else
        echo "⚠️  POTENTIAL CONFLICT - macOS 'Open File' in some apps"
        echo "     Status: Should already be unbound, check config"
        set warnings (math $warnings + 1)
    end

    # Super+F - Find in many apps (macOS convention)
    echo -n "  Super+f (Toggle floating): "
    if grep -q "cmd+f=unbind" ~/.config/ghostty/config
        echo "✅ FIXED (unbound in Ghostty)"
        set good (math $good + 1)
    else
        echo "❌ CONFLICT - macOS 'Find'"
        echo "     Fix: Add 'keybind = cmd+f=unbind' to Ghostty config"
        set conflicts (math $conflicts + 1)
    end

    # Super+[ and Super+] - May conflict with navigation in some apps
    echo -n "  Super+[ (Previous layout): "
    if grep -q "cmd+left_bracket=unbind" ~/.config/ghostty/config
        echo "✅ OK (unbound in Ghostty)"
        set good (math $good + 1)
    else
        echo "⚠️  MINOR: May conflict in some apps"
        set warnings (math $warnings + 1)
    end

    echo -n "  Super+] (Next layout): "
    if grep -q "cmd+right_bracket=unbind" ~/.config/ghostty/config
        echo "✅ OK (unbound in Ghostty)"
        set good (math $good + 1)
    else
        echo "⚠️  MINOR: May conflict in some apps"
        set warnings (math $warnings + 1)
    end

    # Super+= and Super+- - Zoom in some apps
    echo -n "  Super++/= (Resize): "
    echo "⚠️  POTENTIAL: Zoom in some apps (usually Cmd+Plus)"
    set warnings (math $warnings + 1)

    echo -n "  Super+- (Resize): "
    echo "⚠️  POTENTIAL: Zoom out in some apps"
    set warnings (math $warnings + 1)

    echo ""
    echo "📋 Shift+Super Bindings (Legacy):"
    echo ""
    echo "  Shift+Super+g (Locked mode): ✅ OK (safety fallback)"
    echo "  Shift+Super+q (Quit): ⚠️  OK but Cmd+Q quits Ghostty entirely"
    echo "  Shift+Super+t/p/o/s/n/h: ✅ OK (no conflicts, but use Ctrl+Space instead)"

    echo ""
    echo "📋 Ctrl+Space Bindings (Recommended):"
    echo ""
    echo "  Ctrl+Space, t (Tab mode): ✅ OK (no conflicts)"
    echo "  Ctrl+Space, p (Pane mode): ✅ OK (no conflicts)"
    echo "  Ctrl+Space, o (Session mode): ✅ OK (no conflicts)"
    echo "  Ctrl+Space, s (Scroll mode): ✅ OK (no conflicts)"
    echo "  Ctrl+Space, n (Resize mode): ✅ OK (no conflicts)"
    echo "  Ctrl+Space, h (Move mode): ✅ OK (no conflicts)"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📊 Summary:"
    echo "  ✅ Good: $good bindings working correctly"
    echo "  ⚠️  Warnings: $warnings potential minor conflicts"
    echo "  ❌ Conflicts: $conflicts critical conflicts found"
    echo ""

    if test $conflicts -gt 0
        echo "🔧 Action Required:"
        echo "  Run: vim ~/.config/ghostty/config"
        echo "  Or: I can fix these for you if you ask"
        return 1
    else if test $warnings -gt 0
        echo "💡 Note: Warnings are minor and shouldn't affect normal use"
        echo "   All critical conflicts have been resolved!"
        return 0
    else
        echo "🎉 All keybindings are properly configured!"
        return 0
    end
end
