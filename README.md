# zoho-mail-mcp

Servidor MCP para **Zoho Mail** con lo que los MCP genericos de correo no traen:
**multiples cuentas** y **acceso a adjuntos**.

> **Estado: andamiaje.** El servidor existe y funciona, pero su codigo todavia no se ha
> migrado a este repo. Ver [Estado](#estado).

## Por que existe

Los servidores MCP de correo suelen asumir una sola cuenta y exponer solo el cuerpo del
mensaje. En uso real hacen falta dos cosas mas:

- **Multi-cuenta** — varias cuentas de Zoho atendidas en paralelo desde el mismo cliente.
- **Adjuntos** — listarlos y bajarlos, no solo leer texto.

Proyecto hermano para Gmail: [web26-091-gmail-mcp-config](https://github.com/abelardodiaz/web26-091-gmail-mcp-config),
que resuelve el multi-cuenta con wrappers sobre un paquete de terceros. Aqui el servidor es
codigo propio.

## Herramientas previstas

| Herramienta | Que hace |
|---|---|
| `info_cuenta` | datos de la cuenta conectada |
| `listar_carpetas` | carpetas del buzon |
| `listar_correos` | mensajes de una carpeta |
| `buscar_correos` | busqueda |
| `leer_correo` | contenido de un mensaje |
| `listar_adjuntos` | adjuntos de un mensaje |

## Estado

| Pieza | Estado |
|---|---|
| Servidor MCP en uso | funcionando fuera de este repo |
| Codigo migrado aqui | pendiente |
| Empaquetado (`pyproject.toml`) | pendiente |
| Publicado en registry MCP | pendiente |

## Seguridad

Este repo es publico y **no contiene credenciales**. Los tokens OAuth y la configuracion por
cuenta viven fuera de git; `.gitignore` los bloquea explicitamente. Si vas a contribuir,
revisa que tu diff no incluya direcciones de correo reales ni rutas de tu maquina.

## Licencia

Pendiente de definir.
