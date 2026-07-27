#!/usr/bin/env bash
# Doble clic aqui (o ./iniciar.sh) para usar el asistente en Linux o macOS.
# Todo el trabajo lo hace launcher.py; esto solo busca un Python.
set -u
cd "$(dirname "$0")"

PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo
    echo "No encuentro Python instalado."
    echo "En Debian o Ubuntu:  sudo apt install python3 python3-venv"
    echo
    read -r -p "Pulsa Enter para cerrar."
    exit 1
fi

"$PYTHON" launcher.py "$@"
CODE=$?
# Lanzado con doble clic desde el escritorio, la ventana se cierra sola y no
# da tiempo a leer el error.
if [ "$CODE" -ne 0 ] && [ -t 0 ]; then
    echo
    read -r -p "Pulsa Enter para cerrar."
fi
exit "$CODE"
