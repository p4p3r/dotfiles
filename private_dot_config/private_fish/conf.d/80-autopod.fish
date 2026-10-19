# autopod (iPod library automation, ~/Code/p4p3r/autopod): run its venv entry
# point from any directory. Inside the repo, direnv puts it on PATH as well.
if status is-interactive; and test -x ~/Code/p4p3r/autopod/.venv/bin/autopod
    abbr -a -g autopod ~/Code/p4p3r/autopod/.venv/bin/autopod
end
