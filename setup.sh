#!/usr/bin/env bash
# One-command setup for Siesta on Linux and macOS.
#
#   bash setup.sh
#   bash setup.sh --skip-models
#
# Installs a local Ollama runtime (if you do not already have one), pulls the
# three open-weight models Siesta uses, creates a virtualenv and writes the
# local config. Everything lives in your home directory — no root, no
# system service, no account.

set -euo pipefail

SKIP_MODELS=0
SKIP_OLLAMA=0
VISION_MODEL="qwen2.5vl:3b"
TEXT_MODEL="qwen2.5:3b-instruct"
EMBED_MODEL="nomic-embed-text"

for arg in "$@"; do
  case "$arg" in
    --skip-models) SKIP_MODELS=1 ;;
    --skip-ollama) SKIP_OLLAMA=1 ;;
    *) echo "unknown option: $arg" >&2; exit 1 ;;
  esac
done

step()  { printf "\n\033[36m==> %s\033[0m\n" "$1"; }
ok()    { printf "    \033[32mok\033[0m  %s\n" "$1"; }
info()  { printf "    \033[90m..\033[0m  %s\n" "$1"; }

HOME_DIR="$HOME/.siesta"
INBOX="$HOME/Siesta-Inbox"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --------------------------------------------------------------------------- #
step "Checking Python"
if ! command -v python3 >/dev/null 2>&1; then
  echo "    Python 3.10+ is required." >&2
  exit 1
fi
PYVER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
ok "Python $PYVER"

# --------------------------------------------------------------------------- #
if [ "$SKIP_OLLAMA" -eq 0 ]; then
  step "Locating Ollama"
  if command -v ollama >/dev/null 2>&1; then
    ok "found on PATH: $(command -v ollama)"
  else
    info "installing the local Ollama runtime..."
    curl -fsSL https://ollama.com/install.sh | sh
    ok "installed"
  fi

  step "Starting the Ollama server"
  if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    ok "already running"
  else
    (nohup ollama serve >/tmp/ollama-serve.log 2>&1 &)
    for _ in $(seq 1 30); do
      sleep 1
      if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then break; fi
    done
    ok "server is up"
  fi

  if [ "$SKIP_MODELS" -eq 0 ]; then
    step "Pulling open-weight models"
    for model in "$VISION_MODEL" "$TEXT_MODEL" "$EMBED_MODEL"; do
      info "$model ..."
      ollama pull "$model"
    done
    ok "models ready"
  fi
fi

# --------------------------------------------------------------------------- #
step "Setting up the Python environment"
VENV="$PROJECT_ROOT/.venv"
[ -d "$VENV" ] || python3 -m venv "$VENV"
PY="$VENV/bin/python"
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -e ".[dev]"
ok "installed siesta (editable) + dev extras"

# --------------------------------------------------------------------------- #
step "Configuring Siesta"
mkdir -p "$HOME_DIR" "$INBOX"
cat > "$HOME_DIR/config.json" <<JSON
{
  "watch_dir": "$INBOX",
  "vision_model": "$VISION_MODEL",
  "text_model": "$TEXT_MODEL",
  "embed_model": "$EMBED_MODEL"
}
JSON
ok "config written to $HOME_DIR/config.json"

# --------------------------------------------------------------------------- #
printf "\n\033[32mSiesta is ready.\033[0m\n\n"
printf "  1. Drop a photo in  %s\n" "$INBOX"
printf "  2. Run a pass:      .venv/bin/python -m siesta scan\n"
printf "  3. Or the web UI:   .venv/bin/python -m siesta serve\n\n"
printf "Everything runs on this machine. No API key, no account, no network call.\n"
