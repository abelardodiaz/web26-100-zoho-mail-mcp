# zoho-mail-mcp

Servidor MCP para **Zoho Mail** con lo que los MCP genericos de correo no traen:
**multiples cuentas** y **adjuntos de verdad** — subirlos al enviar y bajarlos al leer.

## Por que existe

El MCP oficial de Zoho es remoto y **no puede adjuntar archivos**. No es un problema de
configuracion: un servidor hospedado no tiene acceso a tu disco, y Zoho tampoco expuso su
Upload Attachments API en el catalogo de acciones.

De ahi la regla que dio origen a este proyecto: **si la tarea toca archivos locales,
necesita un componente local.**

Los MCP de correo genericos suelen ademas asumir una sola cuenta y exponer solo el cuerpo
del mensaje. Aqui las dos cosas son el punto: **multi-cuenta** (una instancia por cuenta,
elegida por variable de entorno) y **adjuntos**.

Proyecto hermano para Gmail: [web26-091-gmail-mcp-config](https://github.com/abelardodiaz/web26-091-gmail-mcp-config),
que resuelve el multi-cuenta con wrappers sobre un paquete de terceros. Aqui el servidor es
codigo propio.

## Herramientas

| Herramienta | Que hace |
|---|---|
| `info_cuenta` | alias que la cuenta puede usar como remitente, con su nombre para mostrar |
| `listar_carpetas` | carpetas del buzon con su `folderId` |
| `listar_correos` | mensajes de una carpeta (por nombre o por id) |
| `buscar_correos` | busqueda con la sintaxis de Zoho |
| `leer_correo` | encabezados y cuerpo, convertido a texto plano |
| `listar_adjuntos` | adjuntos de un mensaje, con nombre y tamano |
| `descargar_adjunto` | baja un adjunto a una ruta que **tu** indicas |
| `preparar_correo` | deja un **borrador** y devuelve un id. **No envia** |
| `preparar_respuesta` | igual, respondiendo a un correo existente |
| `enviar_correo` | envia de verdad un preparado, por su id |
| `listar_pendientes` | preparados que siguen esperando confirmacion |
| `descartar_pendiente` | tira un preparado sin enviarlo |

## Enviar es en dos pasos, a proposito

`preparar_correo` sube los adjuntos y deja un **borrador** en Zoho. Nada sale hasta que
llamas `enviar_correo` con el id que devolvio. Asi hay un punto de revision antes de una
accion que no se deshace, y el borrador se puede mirar en la web de Zoho.

El preparado se guarda **en disco**, no en memoria: si el cliente MCP se reinicia entre
preparar y confirmar, el correo (y los adjuntos ya subidos) no se pierden. Confirmar **no
vuelve a subir los adjuntos**.

## Tres reglas que aplica siempre

Las tres salen de errores reales, no de preferencias de estilo:

| Regla | Que previene |
|---|---|
| El remitente se valida contra los alias confirmados de la cuenta | Que un alias inexistente acabe saliendo desde el remitente por defecto |
| El nombre para mostrar se compone desde la config del alias | Que el destinatario vea el correo pelon. **La API no lo aplica sola** |
| El `Reply-To` se fija al remitente | Que las respuestas se vayan a otro dominio |

## Instalacion

Necesitas [uv](https://docs.astral.sh/uv/) y Python 3.12+. Las dependencias van declaradas
en el propio script (PEP 723), asi que no hay que instalar nada aparte.

1. **Credenciales.** Crea un Self Client en la consola de API del centro de datos donde
   vive la cuenta (`api-console.zoho.com`, `api-console.zoho.eu`, ...) y genera un refresh
   token con estos scopes:

   ```
   ZohoMail.messages.CREATE,ZohoMail.messages.READ,ZohoMail.messages.UPDATE,ZohoMail.accounts.READ,ZohoMail.folders.READ
   ```

   Copia `ejemplos/cuenta.example.json` a `~/.zoho-mcp/cuentas/<cuenta>.json`, llenalo y
   dejalo en modo `600`. **Nunca dentro del repo.**

   **Centro de datos.** Una cuenta Zoho solo se autentica contra su propio centro de datos.
   Si no esta en el de EE. UU., pon el campo `region` en el JSON:

   | `region` | Centro de datos | Dominio |
   |---|---|---|
   | `com` (default) | EE. UU. | `zoho.com` |
   | `eu` | Europa | `zoho.eu` |
   | `in` | India | `zoho.in` |
   | `com.au` | Australia | `zoho.com.au` |
   | `jp` | Japon | `zoho.jp` |
   | `ca` | Canada | `zohocloud.ca` |
   | `sa` | Arabia Saudita | `zoho.sa` |
   | `uk` | Reino Unido | `zoho.uk` |

   Se sabe cual es por la URL de la consola de administracion (`mailadmin.zoho.eu` = `eu`).
   Una region que no esta en la tabla se rechaza al arrancar en vez de caer a `com`.

2. **Wrapper.** Copia `wrappers/run-mcp-EJEMPLO.sh`, ajusta las rutas y hazlo ejecutable.

3. **Registralo** en tu cliente MCP:

   ```json
   "zoho-<cuenta>": {
     "type": "stdio",
     "command": "bash",
     "args": ["/ruta/al/run-mcp-<cuenta>.sh"]
   }
   ```

Para varias cuentas: un JSON de credenciales y un wrapper por cada una.

## Pruebas

```bash
./correr-pruebas.sh
```

127 pruebas, ninguna toca la red: la API va contra dobles (`respx`). Lo que si toca correo
real se prueba a mano, porque **un correo enviado no se deshace**.

## Seguridad

Este repo es publico y **no contiene credenciales**. Los tokens OAuth y la configuracion por
cuenta viven fuera de git; `.gitignore` los bloquea explicitamente. Si vas a contribuir,
revisa que tu diff no incluya direcciones de correo reales ni rutas de tu maquina.

Dos decisiones deliberadas sobre permisos:

- **No se pide `ZohoMail.messages.DELETE`.** El borrador que sobra tras enviar se **mueve a
  la papelera**, no se destruye. El servidor nunca tiene permiso de borrar correo sin
  vuelta atras.
- **`descargar_adjunto` exige ruta destino explicita.** No inventa ubicaciones.

## Estado

| Pieza | Estado |
|---|---|
| Servidor MCP | en produccion, 12 herramientas |
| Codigo en este repo | si — este repo es la fuente de verdad |
| Pruebas | 127 en verde |
| Envio real verificado | si, con SPF/DKIM/DMARC en PASS |
| Empaquetado instalable (`uvx`) | pendiente |
| Publicado en registry MCP | pendiente |

## Licencia

Pendiente de definir.

## Repositorios

Este repo se mantiene en dos plataformas, con el mismo contenido en `main`:

- **GitHub (canonico):** https://github.com/abelardodiaz/web26-100-zoho-mail-mcp
- **GitLab (espejo):** https://gitlab.com/abelardodiaz/web26-100-zoho-mail-mcp

Issues y pull requests, en GitHub.
