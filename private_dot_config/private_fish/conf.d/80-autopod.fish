# autopod (iPod library automation, ~/Code/p4p3r/autopod): run its venv entry
# point from any directory. Inside the repo, direnv puts it on PATH as well.
# A function, not an abbr: abbreviations do not expand in pasted commands.
if test -x ~/Code/p4p3r/autopod/.venv/bin/autopod
    function autopod --description 'autopod (~/Code/p4p3r/autopod)'
        ~/Code/p4p3r/autopod/.venv/bin/autopod $argv
    end
end
