function up
   which pipx > /dev/null && pipx upgrade-all
   which brew > /dev/null && brew update && brew upgrade
   which softwareupdate > /dev/null && softwareupdate -d
   which npm > /dev/null && npx npm-check -g -u
end
