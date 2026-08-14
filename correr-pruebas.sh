#!/bin/bash
# Unico comando de pruebas. Encapsula las dependencias de test para que no
# ensucien la cabecera PEP 723 del servidor (esas son las de produccion).
set -euo pipefail
cd "$(dirname "$0")"

UV=$(command -v uv || echo "$HOME/.local/bin/uv")
if [ ! -x "$UV" ]; then
  echo "No encuentro 'uv'. Instalalo: https://docs.astral.sh/uv/" >&2
  exit 1
fi

exec "$UV" run \
  --with "mcp>=2.0,<3" \
  --with "httpx>=0.28,<0.29" \
  --with pytest \
  --with pytest-asyncio \
  --with respx \
  pytest "$@"
