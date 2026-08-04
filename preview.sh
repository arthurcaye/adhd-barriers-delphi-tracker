#!/usr/bin/env bash
# Abre o painel no navegador em http://localhost:8765
#
# Precisa de servidor: abrir o index.html com duplo clique (file://) NAO funciona,
# porque o navegador bloqueia o fetch do data.json em paginas locais.
#
# Ctrl+C para parar.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${1:-8765}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERRO: python3 nao encontrado. No macOS: xcode-select --install"
  exit 1
fi

echo "Painel em http://localhost:${PORT}   (Ctrl+C para parar)"
( sleep 1; command -v open >/dev/null && open "http://localhost:${PORT}" ) &
python3 -m http.server "${PORT}" --bind 127.0.0.1
