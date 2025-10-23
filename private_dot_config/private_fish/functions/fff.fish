function fff
    if test (count $argv) -eq 0
        echo "Need a string to search for!"
        return 1
    end

    # Use the first argument for the search pattern.
    rg --files-with-matches --no-messages $argv[1] | fzf --preview-window $FZF_PREVIEW_WINDOW --preview "rg --ignore-case --pretty --context 10 '$argv[1]' {}"
end
