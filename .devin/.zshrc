# =========================================
# Windsurf project-specific zshrc (macOS)
# =========================================

# Root assoluto del progetto
PROJECT_ROOT="/Users/vinz/VinzAgentsProjects/Ideable"

# Directory dedicata alla history del progetto
HISTDIR="$PROJECT_ROOT/.windsurf-history"
mkdir -p "$HISTDIR"

# File di history isolato
HISTFILE="$HISTDIR/zsh_history"
HISTSIZE=5000
SAVEHIST=5000

# Opzioni di history (valide e supportate)
setopt APPEND_HISTORY
setopt INC_APPEND_HISTORY
setopt NO_SHARE_HISTORY
setopt HIST_IGNORE_DUPS
setopt HIST_REDUCE_BLANKS

# Prompt riconoscibile
PROMPT="(redpanda) %n@%m:%~ %# "

# Posizionamento iniziale nella directory del progetto
cd "$PROJECT_ROOT" || exit 1