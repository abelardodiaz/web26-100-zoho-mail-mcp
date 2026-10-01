# Changelog - web26-100 Zoho Mail MCP

Formato: [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Versionado: [SemVer](https://semver.org/lang/es/).

## [Unreleased]

### Verificado

- **`region: eu` contra la API real** (2026-09-30), con la primera cuenta EU en produccion:
  token 200 en `accounts.zoho.eu`, `GET mail.zoho.eu/api/accounts` 200, remitentes
  resueltos. Hasta aqui el soporte EU solo estaba cubierto por pruebas sin red.

### Docs

- README: la instalacion explica paso a paso como obtener las credenciales (Self Client,
  codigo, canje por refresh token, `accountId`) con el dominio del centro de datos en cada
  URL, y los errores tipicos del canje (`invalid_code`, `invalid_client`).

## [1.1.1] - 2026-09-30

### Fixed

- **Pendientes aislados por cuenta.** `pendientes/` lo comparten todas las instancias y
  cada una veia los borradores de las demas: `listar_pendientes` los mezclaba, y
  `enviar_correo` o `descartar_pendiente` con un id ajeno llegaban a la red (URL de una
  cuenta, token de otra). Ahora cada instancia solo lista, envia y descarta los suyos; con
  un id ajeno falla antes de tocar la red y sin borrar nada. El listado dice cuantos hay
  de otras cuentas, sin mostrar sus destinatarios.
- 8 pruebas nuevas (135 en total).

### Decisiones que conviene no re-descubrir

- **El dueno se deduce de la URL guardada**, no de un campo nuevo. La URL ya lleva region y
  `accountId`, asi que no cambia el formato del archivo y cubre los pendientes escritos
  antes del arreglo. Se compara contra `.../accounts/{id}/` con la barra final, para que la
  cuenta `111` no reclame los de `1112`.
- **Se descarto una carpeta por cuenta**: obligaba a migrar los pendientes existentes y no
  aportaba nada que el filtro no de.

## [1.1.0] - 2026-09-30

### Added

- **Centro de datos por cuenta.** Campo opcional `region` en el JSON de credenciales
  (`com`, `eu`, `in`, `com.au`, `jp`, `ca`, `sa`, `uk`; default `com`). De el salen el
  endpoint de token, el de la API y la consola que citan los mensajes de error. Pedido por
  web26-602 para una cuenta alojada en EU. `info_cuenta` muestra el centro de datos.
- 8 pruebas en `tests/test_region.py` (127 en total).

### Changed

- Los `url_*` reciben la `Cuenta` en vez del `account_id`, y desaparecen las constantes
  `BASE`, `URL_TOKEN` y `URL_CUENTAS`: con una base global era posible armar una URL de
  `.com` para una cuenta EU sin que nada lo notara.

### Decisiones que conviene no re-descubrir

- **Tabla explicita, no `f"zoho.{region}"`.** Canada rompe el patron: es `zohocloud.ca`.
- **Region desconocida = error al arrancar.** Caer a `com` en silencio produce un
  `invalid_client` que no menciona regiones. Ademas el `client_secret` viaja al endpoint
  de token, asi que la region nunca debe poder apuntar a un host arbitrario.
- **Los pendientes guardan la URL completa**, asi que ya quedan atados a su region.

## [1.0.0] - 2026-08-14

Migracion del codigo desde `web25-993`, donde se desarrollo. Este repo pasa a ser la
**fuente de verdad**: el wrapper de produccion ejecuta `src/zoho_mail_mcp.py` desde aqui.

### Added

- **Servidor MCP completo, 12 herramientas** en un archivo con dependencias en linea
  (PEP 723), ejecutado por `uv run --script`. Una instancia por cuenta, elegida con
  `ZOHO_MCP_CUENTA`.
  - Cuenta: `info_cuenta`
  - Lectura: `listar_carpetas`, `listar_correos`, `buscar_correos`, `leer_correo`,
    `listar_adjuntos`, `descargar_adjunto`
  - Envio: `preparar_correo`, `preparar_respuesta`, `enviar_correo`, `listar_pendientes`,
    `descartar_pendiente`
- **119 pruebas** sin red, contra dobles de la API (`respx`).
- `pyproject.toml` con ruff y pytest, plantilla de credenciales en `ejemplos/`, y wrapper
  de ejemplo en `wrappers/`.

### Decisiones que conviene no re-descubrir

- **Patron preparar -> confirmar.** `preparar_*` deja un borrador y devuelve un id;
  `enviar_correo` con ese id es lo unico que manda. Existe `pendientes/` en disco porque
  **Zoho no tiene endpoint para enviar un borrador existente**: se guarda el payload y al
  confirmar se reenvia sin `mode=draft`. Confirmar **no vuelve a subir los adjuntos**.
- **Tres reglas que el servidor aplica siempre**, nacidas de errores reales: validar el
  remitente contra los alias confirmados de la cuenta, componer el nombre para mostrar
  (la API no lo hace sola), y fijar el `Reply-To` al remitente.
- **El borrador se mueve a la papelera tras enviar**, no se borra duro: el borrado duro
  exige `ZohoMail.messages.DELETE`, y no darle ese permiso al servidor es deliberado.
  La limpieza es **best-effort**: cuando corre, el correo ya salio, y reportar su fallo
  como fallo de envio llevaria a reintentar y mandar el correo dos veces.
- **`descargar_adjunto` exige ruta destino explicita.** Un servidor que escribe archivos
  donde le parezca es un problema esperando a ocurrir.
- **stdout es el protocolo MCP.** Todo log va a stderr y el `source` del perfil en el
  wrapper va silenciado; un solo byte de ruido rompe el servidor.

### Hallazgos contra la API real

Varios supuestos razonables resultaron falsos. Estan aqui para que nadie los repita:

- El tamano de un adjunto es **`attachmentSize`**, no `size`. Leerlo de `size` reporta
  **0 KB siempre, en silencio**.
- **`content` no devuelve asunto ni remitente**, solo `messageId` y el cuerpo. Para
  responder a un correo hay que leer **`details`**.
- Las direcciones llegan **con entidades HTML** (`&lt;`, `&quot;`) y `receivedTime` es
  epoch en **milisegundos como cadena**.
- Para borrar: los modos `delete`, `deleteMessage` y `trash` **no existen** (400 *Invalid
  mode*). El que sirve es `moveMessage`, y el campo destino se llama **`destfolderId`**,
  todo en minusculas — `destFolderId`, `destinationFolderId` y `toFolderId` dan
  `EXTRA_KEY_FOUND_IN_JSON`.
- Un **401 por scope faltante** no se arregla renovando el token; se corta de inmediato.
- El **indice de busqueda va con retraso**: para verificar algo recien enviado hay que
  listar la carpeta, no buscar.

### Scopes

```
ZohoMail.messages.CREATE,ZohoMail.messages.READ,ZohoMail.messages.UPDATE,ZohoMail.accounts.READ,ZohoMail.folders.READ
```

**No hace falta `ZohoMail.attachments.READ`** (la descarga va con `messages.READ`) **ni
`ZohoMail.messages.DELETE`** (se mueve a la papelera).

## [0.1.0] - 2026-08-14

### Added
- Andamiaje inicial del repositorio, preparado por claude-996: README, CLAUDE.md,
  PROJECT.yaml, .gitignore y bandeja `docs/incoming`.
- `git init` y primer commit desde el dia uno, para no repetir el hueco reportado por
  99999 el 2026-08-12 (proyectos con codigo real y sin repo).

### Notes
- Sin implementacion todavia. Ver CLAUDE.md para el estado y las decisiones abiertas.
