# FZF default command and options
set -x FZF_DEFAULT_COMMAND 'rg --files --no-ignore-vcs --hidden -g "!{node_modules/,.git/}"'
set -x FZF_COMPLETION_TRIGGER '//'

# FZF default options; multi-line string works in fish if quoted properly.
set -x FZF_DEFAULT_OPTS "
--height=40%
--info=inline
--multi
--layout=reverse
--border
--margin=1
--preview '([[ -f {} ]] && (bat --style=numbers --color=always {} || cat {})) || ([[ -d {} ]] && (tree -C {} | less)) || echo {} 2> /dev/null | head -200'
--color=bg+:#302D41,bg:#1E1E2E,spinner:#F8BD96,hl:#F28FAD
--color=fg:#D9E0EE,header:#F28FAD,info:#DDB6F2,pointer:#F8BD96
--color=marker:#F8BD96,fg+:#F2CDCD,prompt:#DDB6F2,hl+:#F28FAD
--prompt='∼ ' --pointer='▶' --marker='✓'
--bind '?:toggle-preview'
--bind 'ctrl-a:select-all'
--bind 'ctrl-y:execute-silent(echo {+} | pbcopy)'
--bind 'ctrl-e:execute(echo {+} | xargs -o vim)'
--bind 'ctrl-v:execute(code {+})'
"

# Bind a key (here using the literal "ç" character) to the fzf-cd-widget function.
bind 'ç' fzf-cd-widget

set -x FZF_PREVIEW_WINDOW 'right:60%:wrap'
set -x FZF_PREVIEW_ADVANCED true
# set -x LESSOPEN '| lessfilter-fzf %s'
