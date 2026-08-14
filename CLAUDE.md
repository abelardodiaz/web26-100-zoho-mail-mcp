# CLAUDE.md - web26-100 Zoho Mail MCP

Eres **claude-100**, agente de este proyecto.

## Que es esto

Servidor MCP propio para Zoho Mail. Lo que lo justifica frente a un MCP de correo generico
son dos cosas: **multi-cuenta** y **adjuntos**. Si una decision de diseno rompe cualquiera de
las dos, es la decision la que esta mal.

Hermano para Gmail: `public/web26-091-gmail-mcp-config` (wrappers sobre paquete de terceros).
Aqui el servidor es codigo propio.

## Estado y bloqueo

El servidor **ya funciona en produccion fuera de este repo**: es el MCP `zoho-redv6`, en
`/home/wrr/.zoho-mcp/zoho_mail_mcp.py` (WSL), sin git.

**El proyecto 993 esta modificando esa carpeta.** No migres el codigo sin confirmar con el
usuario que 993 termino. Migrar una foto vieja crea exactamente la desincronizacion que este
repo existe para evitar.

Cuando se levante el bloqueo: el **repo es la fuente de verdad** y el wrapper
`run-mcp-redv6.sh` apunta aqui. Nunca dos copias.

## Reglas

- **Repo publico.** Cero credenciales, cero rutas de esta maquina, cero direcciones de correo
  reales. El mapeo real va en `PRIVATE-NOTES.md` (gitignoreado). Revisa cada diff antes de
  commitear.
- **Sin emojis** en scripts bash y python: se corren desde PowerShell en Windows.
- **Ruff obligatorio**: `[tool.ruff]` en `pyproject.toml` + `ruff>=0.8` en dev deps.
- **PROJECT.yaml en cada commit**: `version`, `updated_at`, `updated_by: claude-100`.
- **Dos remotes**: GitHub y GitLab, se pushea a ambos.
- **Postgres, nunca SQLite** (si algun dia hiciera falta persistencia).

## Comunicacion entre proyectos

`docs/incoming/` es la bandeja de memos de otros proyectos de la flota. Al incorporar uno,
**muevelo a `docs/procesados/`** — no lo borres, sirve de auditoria, y si se queda el hook lo
sigue anunciando para siempre.

Para escribirle a otro proyecto, skill `reportar-a-proyecto`. **Nunca edites el codigo ni los
docs de otro proyecto**: esa sesion tiene contexto que la tuya no ve.

## Decisiones abiertas

1. Multi-cuenta: HOME por instancia (patron 091) vs flag `--cuenta` dentro del servidor.
   El codigo es propio, asi que la segunda opcion esta sobre la mesa — decide con argumentos.
2. Empaquetado: entry point instalable (`uvx zoho-mail-mcp`) vs script + wrapper.
3. Licencia (el repo aun no tiene una).
