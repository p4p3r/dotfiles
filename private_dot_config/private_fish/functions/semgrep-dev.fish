function semgrep-dev
    env PIPENV_PIPFILE=~/src/semgrep/semgrep/cli/Pipfile pipenv run semgrep $argv
end
