#!/bin/bash
# Wrapper MCP de Zoho Mail: UNA instancia por cuenta.
#
# Copialo como run-mcp-<cuenta>.sh y ajusta las dos rutas de abajo.
# Registralo en Claude Code como:
#   "zoho-<cuenta>": {"type":"stdio","command":"wsl","args":["/ruta/al/wrapper.sh"]}
#
# El 'source' va silenciado A PROPOSITO: en stdio, stdout ES el protocolo MCP,
# y un solo byte de ruido (un banner, un eco del perfil) rompe el servidor.
{ source "$HOME/.profile"; } >/dev/null 2>&1

# Credenciales de ESTA cuenta. Nunca dentro del repo: el repo es publico.
export ZOHO_MCP_CUENTA="$HOME/.zoho-mcp/cuentas/EJEMPLO.json"

# El codigo vive en el repo, que es la fuente de verdad. Nunca dos copias.
REPO="${ZOHO_MCP_REPO:-$HOME/repos/web26-100-zoho-mail-mcp}"

exec uv run --script "$REPO/src/zoho_mail_mcp.py"
