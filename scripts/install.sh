#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="${PYTHON:-python3}"

fail() {
    printf 'Errore: %s\n' "$1" >&2
    exit 1
}

command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "Python 3 non trovato. Installa Python 3.11+ e riprova."
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
    || fail "È richiesto Python 3.11 o superiore; trovato: $($PYTHON_BIN --version 2>&1)."

if [[ ! -d "$VENV_DIR" ]]; then
    printf 'Creo il virtual environment in %s\n' "$VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR" || fail "Impossibile creare .venv. Su Debian installa il pacchetto python3-venv."
else
    [[ -x "$VENV_DIR/bin/python" ]] || fail "$VENV_DIR esiste ma non è un virtual environment Unix utilizzabile."
fi

VENV_PYTHON="$VENV_DIR/bin/python"
"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel \
    || fail "Aggiornamento di pip/setuptools/wheel non riuscito."
"$VENV_PYTHON" -m pip install -r "$ROOT_DIR/requirements-dev.txt" \
    || fail "Installazione dipendenze non riuscita. Controlla rete e requirements-dev.txt."
"$VENV_PYTHON" -m pip check || fail "Il virtual environment contiene dipendenze incompatibili."
"$VENV_PYTHON" -c 'import flask, PIL; print("Virtual environment verificato:", flask.__version__, PIL.__version__)' \
    || fail "Il virtual environment non riesce a importare Flask e Pillow."

printf '\nInstallazione completata. Per avviare:\n  cd %q\n  source .venv/bin/activate\n  python run.py\n' "$ROOT_DIR"