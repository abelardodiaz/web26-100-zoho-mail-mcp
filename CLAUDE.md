# CLAUDE.md - web26-100 Zoho Mail MCP

Eres **claude-100**, agente de este proyecto.

## Que es esto

Servidor MCP propio para Zoho Mail. Lo que lo justifica frente a un MCP de correo generico
son dos cosas: **multi-cuenta** y **adjuntos**. Si una decision de diseno rompe cualquiera de
las dos, es la decision la que esta mal.

Hermano para Gmail: `public/web26-091-gmail-mcp-config` (wrappers sobre paquete de terceros).
Aqui el servidor es codigo propio.

## Estado

En produccion. El **repo es la fuente de verdad y la unica copia del codigo**: cada instancia
en produccion es un wrapper fuera del repo que ejecuta `src/zoho_mail_mcp.py` desde esta
carpeta. Un cambio aqui llega a produccion al reiniciar el cliente MCP, asi que no se deja
`main` roto. Nunca dos copias del servidor.

Fuera del repo (en `~/.zoho-mcp/` de WSL) viven solo los datos: JSON de credenciales,
wrappers y pendientes. Que instancias existen, de que cuentas y con que rutas, esta en
`PRIVATE-NOTES.md`.

## Reglas

- **Repo publico.** Cero credenciales, cero rutas de esta maquina, cero direcciones de correo
  reales. El mapeo real va en `PRIVATE-NOTES.md` (gitignoreado). Revisa cada diff antes de
  commitear.
- **Sin emojis** en scripts bash y python: se corren desde PowerShell en Windows.
- **Ruff obligatorio**: `[tool.ruff]` en `pyproject.toml` + `ruff>=0.8` en dev deps.
- **PROJECT.yaml en cada commit**: `version`, `updated_at`, `updated_by: claude-100`.
- **Postgres, nunca SQLite** (si algun dia hiciera falta persistencia).

## GitHub y GitLab

Este repo vive en **los dos**, con la convencion de nombres de la flota:

| Remote | Plataforma | URL |
|---|---|---|
| `github` | GitHub | `git@github.com:abelardodiaz/web26-100-zoho-mail-mcp.git` |
| `origin` | GitLab | `git@gitlab.com:abelardodiaz/web26-100-zoho-mail-mcp.git` |

**Ojo con `origin`:** en esta flota `origin` es **GitLab**, no GitHub. El 091 lo hizo al reves
y por eso hay que decirlo. Verifica con `git remote -v` antes de asumir.

### Push: siempre a los dos

```bash
git push github main && git push origin main
```

No es opcional. Un repo pusheado a uno solo se desincroniza en silencio y luego nadie sabe
cual va adelante. Si uno de los dos falla, **no des el trabajo por subido**: arregla y repite.

### Reparto de roles

- **GitHub = cara publica.** Es la URL que se comparte, la que va en `PROJECT.yaml`, la que
  se registra si el servidor se publica en el registry de MCP o en awesome-mcp-servers, y
  donde llegarian issues y PRs de terceros.
- **GitLab = espejo de respaldo.** Misma rama `main`, mismo contenido. Existe para que el
  codigo no dependa de una sola cuenta.

Si algun dia hay que elegir un canonico distinto, se documenta aqui y se explica por que
(precedente: el 050 tiene GitLab como canonico porque F-Droid apunta ahi).

### Ramas y CI

- Rama unica `main`. Si el proyecto crece a ramas de trabajo, se abre PR en **GitHub** y
  GitLab sigue siendo espejo.
- No hay CI configurado. Si se agrega, va en GitHub Actions; GitLab se queda sin pipeline
  para no correr todo dos veces.

### Herramientas

`gh` y `glab` estan autenticados **en WSL**, no en Windows. Desde una sesion en Windows se
usan con `wsl bash -lc "..."` en una sola capa — anidar mas se come la sustitucion de
comandos (leccion conocida de la flota).

Aviso: `glab auth status` puede reportar `Invalid token provided` con un token perfectamente
valido. Antes de concluir que el acceso a GitLab esta roto, comprueba con `glab api user`.

## Comunicacion entre proyectos

`docs/incoming/` es la bandeja de memos de otros proyectos de la flota. Al incorporar uno,
**muevelo a `docs/procesados/`** — no lo borres, sirve de auditoria, y si se queda el hook lo
sigue anunciando para siempre.

Para escribirle a otro proyecto, skill `reportar-a-proyecto`. **Nunca edites el codigo ni los
docs de otro proyecto**: esa sesion tiene contexto que la tuya no ve.

## Decisiones abiertas

1. Empaquetado: entry point instalable (`uvx zoho-mail-mcp`) vs script + wrapper.
2. Licencia (el repo aun no tiene una).

Cerrada: **multi-cuenta = una instancia por cuenta**, elegida con `ZOHO_MCP_CUENTA`. Cada
cuenta trae su `region`, y los pendientes compartidos se filtran por cuenta (v1.1.1).

## Memos enviados

- 2026-09-30 a 602: campo `region` publicado en v1.1.0 (`c701d5a`), con aviso de los pendientes compartidos.
  Archivo `602-20260930233611-from-claude-100-to-claude-602-campo-region-publicado.md`.
  Su primer `info_cuenta` EU es la primera prueba real contra ese DC.
- 2026-09-30 a 602: los pendientes compartidos ya estan resueltos en v1.1.1 (el aviso del
  memo anterior quedo viejo).
- 2026-09-30 a 602: paso a paso de credenciales EU (Self Client, canje, accountId).
