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

1. Multi-cuenta: HOME por instancia (patron 091) vs flag `--cuenta` dentro del servidor.
   El codigo es propio, asi que la segunda opcion esta sobre la mesa — decide con argumentos.
2. Empaquetado: entry point instalable (`uvx zoho-mail-mcp`) vs script + wrapper.
3. Licencia (el repo aun no tiene una).
