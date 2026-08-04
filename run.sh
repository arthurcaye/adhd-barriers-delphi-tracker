#!/usr/bin/env bash
# Atualiza o data.json a partir do REDCap.
#
#   ./run.sh --discover   lista os campos do projeto (rode isso primeiro)
#   ./run.sh              gera o data.json
#
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERRO: python3 nao encontrado."
  echo "No macOS: instale as ferramentas de linha de comando com  xcode-select --install"
  exit 1
fi

if [ ! -f .env ]; then
  echo "ERRO: arquivo .env nao existe."
  echo
  echo "  cp .env.example .env"
  echo "  e cole o token do REDCap dentro dele"
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

if [ -z "${REDCAP_API_TOKEN:-}" ] || [ "${REDCAP_API_TOKEN}" = "cole_o_token_aqui" ]; then
  echo "ERRO: REDCAP_API_TOKEN ainda nao foi preenchido no .env"
  exit 1
fi

python3 redcap_aggregate.py "$@"
