#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "mcp>=2.0,<3",
#   "httpx>=0.28,<0.29",
# ]
# ///
"""Servidor MCP local de Zoho Mail. Una instancia por cuenta.

La cuenta se elige con la variable de entorno ZOHO_MCP_CUENTA, que apunta al
JSON de credenciales. El directorio de trabajo se puede mover con ZOHO_MCP_DIR
(las pruebas lo usan; en produccion no se define).

REGLA NO NEGOCIABLE: stdout es el protocolo MCP. Todo log va a stderr.
"""

from __future__ import annotations

import html
import json
import logging
import mimetypes
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from mcp.server import MCPServer

logging.basicConfig(
    stream=sys.stderr,
    level=os.environ.get("ZOHO_MCP_LOG", "INFO"),
    format="%(asctime)s %(levelname)s zoho-mcp: %(message)s",
)
log = logging.getLogger("zoho-mcp")

# --- 1. Constantes de endpoints -------------------------------------------

# Cada cuenta vive en UN centro de datos de Zoho y solo se autentica contra el
# suyo: un Self Client de api-console.zoho.eu solo canjea tokens en
# accounts.zoho.eu. Tabla explicita y no f"zoho.{region}" porque Canada rompe el
# patron (zohocloud.ca). Fuente: zoho.com/accounts/protocol/oauth/multi-dc.html
DOMINIOS_REGION = {
    "com": "zoho.com",
    "eu": "zoho.eu",
    "in": "zoho.in",
    "com.au": "zoho.com.au",
    "jp": "zoho.jp",
    "ca": "zohocloud.ca",
    "sa": "zoho.sa",
    "uk": "zoho.uk",
}
REGION_DEFAULT = "com"

TIMEOUT_NORMAL = 30.0
TIMEOUT_SUBIDA = 180.0
DIAS_PURGA_PENDIENTES = 7

DIR_BASE = Path(os.environ.get("ZOHO_MCP_DIR", str(Path.home() / ".zoho-mcp")))
DIR_PENDIENTES = DIR_BASE / "pendientes"

TOPE_LISTADO = 100


def url_carpetas(c: Cuenta) -> str:
    return f"{c.api}/accounts/{c.account_id}/folders"


def url_vista(c: Cuenta) -> str:
    return f"{c.api}/accounts/{c.account_id}/messages/view"


def url_busqueda(c: Cuenta) -> str:
    return f"{c.api}/accounts/{c.account_id}/messages/search"


def url_contenido(c: Cuenta, fid: str, mid: str) -> str:
    return f"{c.api}/accounts/{c.account_id}/folders/{fid}/messages/{mid}/content"


def url_detalles(c: Cuenta, fid: str, mid: str) -> str:
    return f"{c.api}/accounts/{c.account_id}/folders/{fid}/messages/{mid}/details"


def url_info_adjuntos(c: Cuenta, fid: str, mid: str) -> str:
    return f"{c.api}/accounts/{c.account_id}/folders/{fid}/messages/{mid}/attachmentinfo"


def url_bajar_adjunto(c: Cuenta, fid: str, mid: str, att: str) -> str:
    return f"{c.api}/accounts/{c.account_id}/folders/{fid}/messages/{mid}/attachments/{att}"


def url_subir(c: Cuenta) -> str:
    return f"{c.api}/accounts/{c.account_id}/messages/attachments"


def url_enviar(c: Cuenta) -> str:
    return f"{c.api}/accounts/{c.account_id}/messages"


def url_responder(c: Cuenta, mid: str) -> str:
    return f"{c.api}/accounts/{c.account_id}/messages/{mid}"


def url_actualizar(c: Cuenta) -> str:
    """Borrar un mensaje va por aqui. Se eligio sobre
    DELETE /folders/{fid}/messages/{mid} porque NO pide folderId, que sin el
    scope de carpetas no siempre se puede averiguar."""
    return f"{c.api}/accounts/{c.account_id}/updatemessage"


# --- 2. Errores y modelos -------------------------------------------------


class ZohoError(Exception):
    """Error que se le muestra al usuario tal cual. Sin trazas ni jerga."""


class ErrorAuth(ZohoError):
    """Credencial rota. No se reintenta: reintentar contra auth bloquea la cuenta."""


@dataclass(frozen=True)
class Cuenta:
    nombre: str
    client_id: str
    client_secret: str
    refresh_token: str
    account_id: str
    limite_adjunto_mb: int = 20
    region: str = REGION_DEFAULT

    @property
    def dominio(self) -> str:
        return DOMINIOS_REGION[self.region]

    @property
    def api(self) -> str:
        return f"https://mail.{self.dominio}/api"

    @property
    def url_token(self) -> str:
        return f"https://accounts.{self.dominio}/oauth/v2/token"

    @property
    def url_cuentas(self) -> str:
        return f"{self.api}/accounts"

    @property
    def consola(self) -> str:
        return f"api-console.{self.dominio}"


@dataclass(frozen=True)
class Remitente:
    correo: str
    nombre: str


# --- 3. Config de cuenta --------------------------------------------------


def cargar_cuenta(ruta: str | None = None) -> Cuenta:
    ruta = ruta or os.environ.get("ZOHO_MCP_CUENTA", "")
    if not ruta:
        raise ZohoError(
            "Falta la variable de entorno ZOHO_MCP_CUENTA con la ruta al JSON de credenciales"
        )
    p = Path(ruta)
    if not p.is_file():
        raise ZohoError(f"No existe el archivo de credenciales: {p}")
    modo = p.stat().st_mode & 0o077
    if modo:
        log.warning("permisos flojos en %s; deberia ser 600", p)
    datos = json.loads(p.read_text(encoding="utf-8"))
    faltan = [
        c
        for c in ("nombre", "client_id", "client_secret", "refresh_token", "account_id")
        if not datos.get(c)
    ]
    if faltan:
        raise ZohoError(f"Al archivo {p} le faltan campos: {', '.join(faltan)}")
    region = str(datos.get("region") or REGION_DEFAULT).strip().lower()
    if region not in DOMINIOS_REGION:
        # Se rechaza en vez de caer a .com: una cuenta EU contra .com falla con
        # un invalid_client que no dice nada de regiones.
        raise ZohoError(
            f"Region '{region}' desconocida en {p}. Validas: {', '.join(DOMINIOS_REGION)}"
        )
    return Cuenta(
        nombre=datos["nombre"],
        client_id=datos["client_id"],
        client_secret=datos["client_secret"],
        refresh_token=datos["refresh_token"],
        account_id=str(datos["account_id"]),
        limite_adjunto_mb=int(datos.get("limite_adjunto_mb", 20)),
        region=region,
    )


# --- 4. Auth y cliente HTTP -----------------------------------------------


class Auth:
    def __init__(self, cuenta: Cuenta, cliente: httpx.AsyncClient) -> None:
        self.cuenta = cuenta
        self._cliente = cliente
        self._token: str | None = None
        self._expira = 0.0
        self._muerto: str | None = None

    async def token(self, forzar: bool = False) -> str:
        if self._muerto:
            raise ErrorAuth(self._muerto)
        if not forzar and self._token and time.monotonic() < self._expira - 60:
            return self._token
        r = await self._cliente.post(
            self.cuenta.url_token,
            data={
                "grant_type": "refresh_token",
                "client_id": self.cuenta.client_id,
                "client_secret": self.cuenta.client_secret,
                "refresh_token": self.cuenta.refresh_token,
            },
            timeout=TIMEOUT_NORMAL,
        )
        datos = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if "access_token" not in datos:
            error = str(datos.get("error", f"HTTP {r.status_code}"))
            self._muerto = (
                f"Zoho rechazo el refresh token de la cuenta '{self.cuenta.nombre}' ({error}). "
                f"Regeneralo en {self.cuenta.consola} con los scopes ZohoMail.messages.CREATE, "
                "ZohoMail.messages.READ y ZohoMail.accounts.READ, y actualiza el JSON de "
                "credenciales. No se reintentara en esta sesion."
            )
            raise ErrorAuth(self._muerto)
        self._token = str(datos["access_token"])
        self._expira = time.monotonic() + float(datos.get("expires_in", 3600))
        log.info("access token renovado, vence en %ss", datos.get("expires_in", 3600))
        return self._token

    async def peticion(
        self,
        metodo: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        reintento: bool = True,
        timeout: float = TIMEOUT_NORMAL,
        **kw,
    ) -> httpx.Response:
        cab = dict(headers or {})
        cab["Authorization"] = f"Zoho-oauthtoken {await self.token()}"
        r = await self._cliente.request(metodo, url, headers=cab, timeout=timeout, **kw)
        if r.status_code == 401 and "INVALID_OAUTHSCOPE" in r.text:
            # Un scope faltante no se arregla renovando el token. Reintentar solo
            # gasta una llamada y ensucia el diagnostico.
            raise ZohoError(f"Zoho respondio 401 en {metodo} {url}: {r.text[:400]}")
        if r.status_code == 401 and reintento:
            log.info("401 en %s; renovando token y reintentando una vez", url)
            await self.token(forzar=True)
            return await self.peticion(
                metodo, url, headers=headers, reintento=False, timeout=timeout, **kw
            )
        if r.status_code >= 400:
            raise ZohoError(f"Zoho respondio {r.status_code} en {metodo} {url}: {r.text[:400]}")
        return r


def extraer_remitentes(datos_cuenta: dict) -> list[Remitente]:
    salida: list[Remitente] = []
    for d in datos_cuenta.get("sendMailDetails", []) or []:
        correo = (d.get("fromAddress") or "").strip()
        if correo:
            salida.append(Remitente(correo, (d.get("displayName") or "").strip()))
    return salida


# --- 5. Formato, rutas y validaciones puras -------------------------------

_RE_WINDOWS = re.compile(r"^([A-Za-z]):[\\/](.*)$")


def normalizar_ruta(ruta: str) -> Path:
    """Acepta rutas de Windows porque el cliente es Windows y el servidor WSL.
    Es la misma frontera que en la Fase 1 se comio un refresh token."""
    limpia = str(ruta or "").strip().strip('"').strip("'").strip()
    if not limpia:
        raise ZohoError("La ruta vino vacia; dame la ruta completa del archivo")
    m = _RE_WINDOWS.match(limpia)
    if m:
        return Path(f"/mnt/{m.group(1).lower()}/{m.group(2).replace(chr(92), '/')}")
    return Path(limpia).expanduser()


def validar_destino(ruta: str, sobrescribir: bool = False) -> Path:
    p = normalizar_ruta(ruta)
    if p.is_dir():
        raise ZohoError(
            f"El destino {p} es un directorio; dame la ruta completa con nombre de archivo"
        )
    if not p.parent.is_dir():
        raise ZohoError(f"El directorio destino no existe: {p.parent}")
    if p.exists() and not sobrescribir:
        raise ZohoError(
            f"Ya existe un archivo en {p}. Elige otro nombre, o pasa sobrescribir=True "
            "si de verdad quieres reemplazarlo."
        )
    return p


def nombre_seguro(nombre: str) -> str:
    """El attachmentName lo elige quien manda el correo: es entrada no confiable.
    Solo se conserva el ultimo tramo, para que un '../..' no escape del destino."""
    limpio = str(nombre or "").replace(chr(92), "/").split("/")[-1].strip()
    return limpio or "adjunto"


@dataclass(frozen=True)
class AdjuntoSubido:
    nombre: str
    ruta: str
    store: str
    bytes_: int


def validar_adjuntos(rutas: list[str] | None, limite_mb: int) -> list[tuple[Path, int]]:
    """Todo se valida ANTES de tocar la red. Un fallo a media subida deja un
    borrador con la mitad de los archivos y pinta de completo."""
    limite = limite_mb * 1024 * 1024
    salida: list[tuple[Path, int]] = []
    total = 0
    for ruta in rutas or []:
        p = normalizar_ruta(ruta)
        if not p.is_file():
            raise ZohoError(f"No existe o no es un archivo: {p}")
        if not os.access(p, os.R_OK):
            raise ZohoError(f"Sin permiso de lectura sobre: {p}")
        tam = p.stat().st_size
        if tam == 0:
            raise ZohoError(f"El archivo esta vacio: {p}")
        if tam > limite:
            raise ZohoError(
                f"El archivo {p.name} pesa {tam / 1024 / 1024:.1f} MB y el limite "
                f"de esta cuenta es {limite_mb} MB"
            )
        total += tam
        salida.append((p, tam))
    if total > limite:
        raise ZohoError(
            f"Los {len(salida)} archivos suman {total / 1024 / 1024:.1f} MB y el limite "
            f"de esta cuenta es {limite_mb} MB"
        )
    return salida


# --- 6. Composicion del payload -------------------------------------------
#
# Las tres reglas de este bloque salen de errores reales observados el
# 2026-08-05 al mandar por el MCP remoto. No son preferencias de estilo.

FORMATOS = ("html", "plaintext")

_RE_CORREO_EN_FROM = re.compile(r"<([^>]+)>")


def resolver_remitente(alias: str, remitentes: list[Remitente]) -> Remitente:
    """REGLA 1: el remitente se valida contra los alias confirmados de la cuenta.
    Sin esto, Zoho acepta cualquier cosa y manda desde el remitente predeterminado."""
    crudo = str(alias or "").strip()
    m = _RE_CORREO_EN_FROM.search(crudo)
    if m:  # por si llega ya compuesto como 'Nombre <correo>'
        crudo = m.group(1)
    objetivo = crudo.strip().lower()
    if not objetivo:
        raise ZohoError(
            "Falta el remitente. Usa info_cuenta para ver los alias disponibles."
        )
    for r in remitentes:
        if r.correo.lower() == objetivo:
            return r
    disponibles = ", ".join(r.correo for r in remitentes)
    raise ZohoError(
        f"'{alias}' no es un alias confirmado de esta cuenta. Disponibles: {disponibles}"
    )


def componer_from(remitente: Remitente) -> str:
    """REGLA 2: el nombre para mostrar se compone desde la config del alias.
    La API no lo aplica sola: sin esto el destinatario ve el correo pelon."""
    nombre = remitente.nombre.replace('"', "").strip()
    if not nombre:
        return remitente.correo
    return f'"{nombre}" <{remitente.correo}>'


def normalizar_destinatarios(valor: object) -> list[str]:
    """Acepta lista o cadena separada por comas o punto y coma, porque quien
    llama es un modelo y va a mandar las dos formas."""
    if valor is None:
        crudos: list[str] = []
    elif isinstance(valor, str):
        crudos = re.split(r"[,;]", valor)
    else:
        crudos = [str(v) for v in valor]
    salida: list[str] = []
    for c in crudos:
        correo = c.strip().strip("<>").strip()
        if not correo:
            continue
        if "@" not in correo or " " in correo:
            raise ZohoError(f"'{correo}' no parece un correo valido")
        if correo not in salida:
            salida.append(correo)
    return salida


def construir_payload(
    *,
    remitente: Remitente,
    para: list[str],
    cc: list[str],
    cco: list[str],
    asunto: str,
    cuerpo: str,
    formato: str,
    adjuntos: list[AdjuntoSubido],
) -> dict:
    if formato not in FORMATOS:
        raise ZohoError(f"El formato debe ser uno de {FORMATOS}, no '{formato}'")
    if not str(asunto or "").strip():
        raise ZohoError("El correo necesita un asunto")
    para = normalizar_destinatarios(para)
    cc = normalizar_destinatarios(cc)
    cco = normalizar_destinatarios(cco)
    if not (para or cc or cco):
        raise ZohoError("El correo necesita al menos un destinatario")

    payload: dict = {
        "fromAddress": componer_from(remitente),
        # REGLA 3: el Reply-To se fija explicitamente. La interfaz web de Zoho
        # arrastra uno propio y las respuestas se van a otro dominio.
        "replyTo": remitente.correo,
        "subject": str(asunto).strip(),
        "content": str(cuerpo),
        "mailFormat": formato,
    }
    if para:
        payload["toAddress"] = ",".join(para)
    if cc:
        payload["ccAddress"] = ",".join(cc)
    if cco:
        payload["bccAddress"] = ",".join(cco)
    if adjuntos:
        payload["attachments"] = [
            {"attachmentName": a.nombre, "attachmentPath": a.ruta, "storeName": a.store}
            for a in adjuntos
        ]
    # Sin 'mode' a proposito: distingue borrador de envio y lo pone quien llama.
    # Guardarlo aqui haria que confirmar creara otro borrador en vez de mandar.
    return payload


# --- 5b. Formato de lectura -----------------------------------------------


def ref_mensaje(folder_id: str, message_id: str) -> str:
    """La API pide carpeta Y mensaje para leer. Se emiten juntos para que quien
    lista no tenga que adivinar la carpeta despues."""
    return f"{folder_id}/{message_id}"


def parse_ref(ref: str) -> tuple[str, str]:
    partes = str(ref).strip().split("/")
    if len(partes) != 2 or not all(p.strip() for p in partes):
        raise ZohoError(
            f"'{ref}' no es una referencia valida. Se espera el formato carpeta/mensaje "
            "tal como lo devuelve listar_correos o buscar_correos."
        )
    return partes[0].strip(), partes[1].strip()


def fecha_legible(epoch_ms: str) -> str:
    """Zoho entrega epoch en milisegundos como cadena. Si viene algo raro se
    devuelve tal cual: una fecha fea es mejor que una herramienta caida."""
    try:
        return datetime.fromtimestamp(int(epoch_ms) / 1000).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError, OverflowError):
        return str(epoch_ms)


def _limpio(valor: object) -> str:
    """La API devuelve direcciones con entidades HTML (&lt;, &quot;)."""
    return html.unescape(str(valor or "")).strip()


def formatear_lista(mensajes: list[dict]) -> str:
    if not mensajes:
        return "Sin mensajes."
    lineas = []
    for m in mensajes:
        ref = ref_mensaje(str(m.get("folderId", "")), str(m.get("messageId", "")))
        marca = " [adj]" if str(m.get("hasAttachment", "0")) == "1" else ""
        lineas.append(
            f"[{ref}] {fecha_legible(m.get('receivedTime', ''))} | "
            f"de: {_limpio(m.get('fromAddress'))} | "
            f"{_limpio(m.get('subject')) or '(sin asunto)'}{marca}"
        )
    return "\n".join(lineas)


def tam_legible(n: int) -> str:
    """Un archivo de 79 bytes mostrado como '0 KB' parece un error aunque no lo sea."""
    n = int(n or 0)
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def formatear_adjuntos(datos: dict) -> str:
    adjuntos = (datos or {}).get("attachments") or []
    if not adjuntos:
        return "Ese correo no tiene adjuntos."
    return "\n".join(
        f"[{a.get('attachmentId')}] {a.get('attachmentName')} "
        f"({tam_legible(a.get('attachmentSize', 0))})"
        for a in adjuntos
    )


_RE_BLOQUE_MUERTO = re.compile(
    r"<(style|script|head)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL
)
_RE_SALTO = re.compile(r"<\s*(br|/p|/div|/tr|/h[1-6])\b[^>]*>", re.IGNORECASE)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_LINEAS_VACIAS = re.compile(r"\n{3,}")


def html_a_texto(bruto: str) -> str:
    """El cuerpo llega como HTML completo, con CSS incluido. Sin esto, leer un
    correo gasta miles de tokens en hojas de estilo que no le dicen nada a nadie."""
    txt = _RE_BLOQUE_MUERTO.sub(" ", str(bruto or ""))
    txt = _RE_SALTO.sub("\n", txt)
    txt = _RE_TAG.sub("", txt)
    txt = html.unescape(txt).replace("\xa0", " ").replace("\r", "")
    txt = "\n".join(linea.strip() for linea in txt.split("\n"))
    return _RE_LINEAS_VACIAS.sub("\n\n", txt).strip()


def carpeta_es_id(carpeta: str) -> bool:
    """Los folderId de Zoho son enteros largos. Aceptarlos directo permite
    trabajar sin el scope de carpetas."""
    return str(carpeta).strip().isdigit()


def buscar_carpeta(nombre: str, carpetas: list[dict]) -> str:
    objetivo = str(nombre).strip().lower()
    for c in carpetas:
        if str(c.get("folderName", "")).lower() == objetivo:
            return str(c["folderId"])
    disponibles = ", ".join(str(c.get("folderName")) for c in carpetas)
    raise ZohoError(f"No existe la carpeta '{nombre}'. Disponibles: {disponibles}")


def explicar_scope_carpetas(error: Exception, consola: str) -> str | None:
    """Traduce el INVALID_OAUTHSCOPE de /folders a algo que se pueda accionar.
    Devuelve None si el error es otro, para no disfrazar fallos distintos."""
    if "INVALID_OAUTHSCOPE" not in str(error):
        return None
    return (
        "El refresh token de esta cuenta no incluye el scope ZohoMail.folders.READ, "
        "asi que no se pueden listar las carpetas por nombre. Dos salidas: "
        "(a) pasar el folderId numerico directamente a listar_correos, que si funciona; "
        f"(b) regenerar el refresh token en {consola} agregando "
        "ZohoMail.folders.READ a los scopes."
    )


# --- 7. Pendientes en disco -----------------------------------------------
# Van a disco y no a memoria: si Claude Code reinicia entre preparar y
# confirmar, el correo (y los adjuntos ya subidos a Zoho) no se pierden.
# Zoho no tiene endpoint para enviar un borrador existente; por eso guardamos
# el payload y al confirmar lo reenviamos sin mode=draft.

_RE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def _ruta_pendiente(ident: str) -> Path:
    texto = str(ident or "")
    if not _RE_ID.match(texto) or ".." in texto:
        raise ZohoError(f"'{ident}' no es un identificador de pendiente valido")
    return DIR_PENDIENTES / f"{texto}.json"


def guardar_pendiente(
    url: str, payload: dict, resumen: str, borrador_id: str = ""
) -> str:
    DIR_PENDIENTES.mkdir(parents=True, exist_ok=True)
    ahora = datetime.now(UTC)
    ident = f"{ahora.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    destino = _ruta_pendiente(ident)
    contenido = {
        "id": ident,
        "creado": ahora.isoformat(),
        "url": url,
        "payload": payload,
        "resumen": resumen,
        # Para poder borrar el borrador que Zoho conserva tras enviar.
        "borrador_id": borrador_id,
    }
    tmp = destino.with_suffix(".tmp")
    # os.open con modo 600 desde el inicio: escribir y despues hacer chmod deja
    # una ventana en la que el archivo es legible por todos.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(contenido, f, ensure_ascii=False, indent=2)
    tmp.replace(destino)  # atomico: nunca se lee un pendiente a medio escribir
    return ident


def es_de_cuenta(pendiente: dict, c: Cuenta) -> bool:
    """El directorio de pendientes lo comparten todas las instancias. La URL
    guardada ya dice region y accountId, asi que sirve de dueno sin agregar
    campos, y cubre tambien los pendientes escritos antes de este chequeo."""
    return str(pendiente.get("url", "")).startswith(f"{c.api}/accounts/{c.account_id}/")


def leer_pendiente(ident: str, c: Cuenta) -> dict:
    p = _ruta_pendiente(ident)
    if not p.is_file():
        raise ZohoError(
            f"No hay un pendiente con id '{ident}'. Puede que ya se haya enviado, "
            "descartado o purgado por antiguedad."
        )
    try:
        datos = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ZohoError(f"El pendiente '{ident}' esta ilegible: {e}") from e
    if not isinstance(datos, dict) or "payload" not in datos or "url" not in datos:
        raise ZohoError(f"El pendiente '{ident}' esta ilegible: le faltan campos")
    if not es_de_cuenta(datos, c):
        # Sin esto, otra instancia lo mandaria con su token contra la URL ajena,
        # o lo descartaria borrando un borrador que no es suyo.
        raise ZohoError(
            f"El pendiente '{ident}' es de otra cuenta, no de '{c.nombre}'. "
            "Envialo o descartalo desde la instancia de esa cuenta."
        )
    return datos


def borrar_pendiente(ident: str) -> None:
    _ruta_pendiente(ident).unlink(missing_ok=True)


def listar_pendientes_texto(c: Cuenta) -> str:
    """Sin esto, un reinicio de Claude Code deja el id fuera de la conversacion
    y el pendiente queda inalcanzable hasta que lo purgue el tiempo."""
    if not DIR_PENDIENTES.is_dir():
        return "Sin correos pendientes."
    lineas = []
    ajenos = 0
    for p in sorted(DIR_PENDIENTES.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue  # un archivo roto no debe ocultar los sanos
        if not isinstance(d, dict):
            continue
        if not es_de_cuenta(d, c):
            ajenos += 1
            continue
        lineas.append(f"[{d.get('id', p.stem)}] {d.get('creado', '')} | {d.get('resumen', '')}")
    salida = "\n".join(lineas) if lineas else "Sin correos pendientes."
    if ajenos:
        # Solo el conteo: los resumenes llevan destinatarios de la otra cuenta.
        salida += f"\n({ajenos} pendiente(s) de otras cuentas, no se muestran)"
    return salida


def purgar_pendientes() -> int:
    """Se corre al arrancar. Devuelve cuantos borro."""
    if not DIR_PENDIENTES.is_dir():
        return 0
    limite = time.time() - DIAS_PURGA_PENDIENTES * 86400
    n = 0
    for p in DIR_PENDIENTES.glob("*.json"):
        if p.stat().st_mtime < limite:
            p.unlink(missing_ok=True)
            n += 1
    if n:
        log.info("purgados %s pendientes de mas de %s dias", n, DIAS_PURGA_PENDIENTES)
    return n


# --- 8. Herramientas MCP --------------------------------------------------

SERVIDOR = MCPServer(name="zoho-mail", version="1.1.1")

_CUENTA: Cuenta | None = None
_CLIENTE: httpx.AsyncClient | None = None
_AUTH: Auth | None = None
_REMITENTES: list[Remitente] | None = None


def auth() -> Auth:
    global _CUENTA, _CLIENTE, _AUTH
    if _AUTH is None:
        _CUENTA = cargar_cuenta()
        _CLIENTE = httpx.AsyncClient(timeout=TIMEOUT_NORMAL)
        _AUTH = Auth(_CUENTA, _CLIENTE)
    return _AUTH


def cuenta() -> Cuenta:
    auth()
    assert _CUENTA is not None
    return _CUENTA


async def remitentes() -> list[Remitente]:
    """Alias confirmados de la cuenta. Se piden una vez por proceso."""
    global _REMITENTES
    if _REMITENTES is None:
        r = await auth().peticion("GET", cuenta().url_cuentas)
        cuentas = r.json().get("data", []) or []
        mia = next(
            (c for c in cuentas if str(c.get("accountId")) == cuenta().account_id),
            cuentas[0] if cuentas else {},
        )
        _REMITENTES = extraer_remitentes(mia)
        if not _REMITENTES:
            raise ZohoError(
                "Zoho no devolvio ningun remitente confirmado para esta cuenta; "
                "revisa el account_id del archivo de credenciales"
            )
    return _REMITENTES


@SERVIDOR.tool(
    description=(
        "Muestra los alias que esta cuenta puede usar como remitente, con su nombre "
        "para mostrar. Usalo antes de preparar un correo si no sabes desde que "
        "direccion mandarlo."
    )
)
async def info_cuenta() -> str:
    c = cuenta()
    lineas = [
        f"Cuenta: {c.nombre} (accountId {c.account_id})",
        f"Centro de datos: {c.dominio}",
        f"Limite de adjunto: {c.limite_adjunto_mb} MB",
        "Remitentes disponibles:",
    ]
    for r in await remitentes():
        detalle = f'  (nombre: "{r.nombre}")' if r.nombre else "  (SIN nombre para mostrar)"
        lineas.append(f"  - {r.correo}{detalle}")
    return "\n".join(lineas)


async def _carpetas() -> list[dict]:
    try:
        r = await auth().peticion("GET", url_carpetas(cuenta()))
    except ZohoError as e:
        explicacion = explicar_scope_carpetas(e, cuenta().consola)
        raise ZohoError(explicacion) from e if explicacion else e
    return r.json().get("data", []) or []


async def _resolver_carpeta(carpeta: str) -> str:
    if carpeta_es_id(carpeta):
        return str(carpeta).strip()
    return buscar_carpeta(carpeta, await _carpetas())


def _tope(limite: int) -> int:
    return max(1, min(int(limite), TOPE_LISTADO))


@SERVIDOR.tool(
    description=(
        "Lista las carpetas del buzon con su folderId. Requiere el scope "
        "ZohoMail.folders.READ; si falta, usa los folderId que ya vienen en las "
        "referencias de listar_correos."
    )
)
async def listar_carpetas() -> str:
    carpetas = await _carpetas()
    if not carpetas:
        return "Zoho no devolvio carpetas."
    return "\n".join(
        f"[{c.get('folderId')}] {c.get('folderName')}" for c in carpetas
    )


@SERVIDOR.tool(
    description=(
        "Lista los correos de una carpeta. Acepta el nombre ('Inbox') o el "
        "folderId numerico. Sin argumentos lista los mas recientes del buzon. "
        "Devuelve una referencia [carpeta/mensaje] por linea, que es exactamente "
        "lo que piden leer_correo y listar_adjuntos."
    )
)
async def listar_correos(carpeta: str = "", limite: int = 20) -> str:
    params: dict[str, object] = {"limit": _tope(limite), "start": 1}
    if str(carpeta).strip():
        params["folderId"] = await _resolver_carpeta(carpeta)
    r = await auth().peticion("GET", url_vista(cuenta()), params=params)
    return formatear_lista(r.json().get("data", []) or [])


@SERVIDOR.tool(
    description=(
        "Busca correos con la sintaxis de Zoho, por ejemplo 'entire:factura', "
        "'sender:cliente@dominio.com' o 'subject:cotizacion'."
    )
)
async def buscar_correos(consulta: str, limite: int = 20) -> str:
    r = await auth().peticion(
        "GET",
        url_busqueda(cuenta()),
        params={"searchKey": consulta, "limit": _tope(limite), "start": 1},
    )
    return formatear_lista(r.json().get("data", []) or [])


@SERVIDOR.tool(
    description=(
        "Lee un correo por su referencia carpeta/mensaje: devuelve los "
        "encabezados y el cuerpo convertido a texto plano. Pasa crudo=True solo "
        "si necesitas el HTML original (es mucho mas largo)."
    )
)
async def leer_correo(referencia: str, crudo: bool = False) -> str:
    fid, mid = parse_ref(referencia)
    c = cuenta()
    det = (await auth().peticion("GET", url_detalles(c, fid, mid))).json().get("data", {}) or {}
    cont = (await auth().peticion("GET", url_contenido(c, fid, mid))).json().get("data", {}) or {}
    cabecera = [
        f"De:      {_limpio(det.get('fromAddress'))}",
        f"Para:    {_limpio(det.get('toAddress'))}",
        f"Fecha:   {fecha_legible(det.get('receivedTime', ''))}",
        f"Asunto:  {_limpio(det.get('subject')) or '(sin asunto)'}",
    ]
    if _limpio(det.get("ccAddress")) not in ("", "Not Provided"):
        cabecera.insert(2, f"CC:      {_limpio(det.get('ccAddress'))}")
    if str(det.get("hasAttachment", "0")) == "1":
        cabecera.append("Adjuntos: si (usa listar_adjuntos para verlos)")
    cuerpo = cont.get("content") or det.get("summary") or "(sin cuerpo)"
    if not crudo:
        cuerpo = html_a_texto(cuerpo)
    return "\n".join(cabecera) + "\n\n---\n" + str(cuerpo)


@SERVIDOR.tool(
    description="Lista los adjuntos de un correo, con nombre, tamano e identificador."
)
async def listar_adjuntos(referencia: str) -> str:
    fid, mid = parse_ref(referencia)
    r = await auth().peticion("GET", url_info_adjuntos(cuenta(), fid, mid))
    return formatear_adjuntos(r.json().get("data", {}) or {})


@SERVIDOR.tool(
    description=(
        "Descarga un adjunto a una ruta destino que TU debes indicar, incluyendo "
        "el nombre del archivo. Acepta rutas de Windows como C:\\Users\\tu-usuario\\x.pdf; "
        "el servidor las traduce. No inventa ubicaciones ni pisa archivos existentes "
        "salvo que pases sobrescribir=True."
    )
)
async def descargar_adjunto(
    referencia: str,
    id_adjunto: str,
    ruta_destino: str,
    sobrescribir: bool = False,
) -> str:
    fid, mid = parse_ref(referencia)
    # Todo se valida antes de tocar la red: bajar 20 MB para descubrir que el
    # directorio no existe es tiempo tirado.
    destino = validar_destino(ruta_destino, sobrescribir=sobrescribir)
    r = await auth().peticion(
        "GET",
        url_bajar_adjunto(cuenta(), fid, mid, str(id_adjunto).strip()),
        timeout=TIMEOUT_SUBIDA,
    )
    datos = r.content
    if not datos:
        raise ZohoError(
            "Zoho devolvio un adjunto vacio. Verifica el id con listar_adjuntos; "
            "no se escribio nada en disco."
        )
    destino.write_bytes(datos)
    return f"Escrito {destino} ({tam_legible(len(datos))})"


async def _subir_adjuntos(archivos: list[tuple[Path, int]]) -> list[AdjuntoSubido]:
    """Sube de a uno para poder decir CUAL fallo. Abortar limpio es mejor que
    dejar un borrador a medias que parezca completo."""
    subidos: list[AdjuntoSubido] = []
    for p, tam in archivos:
        tipo = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        try:
            r = await auth().peticion(
                "POST",
                url_subir(cuenta()),
                params={"uploadType": "multipart"},
                files={"attach": (p.name, p.read_bytes(), tipo)},
                timeout=TIMEOUT_SUBIDA,
            )
        except ZohoError as e:
            raise ZohoError(
                f"Fallo la subida de '{p.name}': {e}. No se creo ningun borrador; "
                "vuelve a intentar el correo completo."
            ) from e
        datos = r.json().get("data") or []
        if not datos:
            raise ZohoError(f"Zoho no devolvio referencia para '{p.name}': {r.text[:300]}")
        d = datos[0]
        subidos.append(
            AdjuntoSubido(
                nombre=d.get("attachmentName", p.name),
                ruta=d["attachmentPath"],
                store=d["storeName"],
                bytes_=int(d.get("attachmentSize") or tam),
            )
        )
        log.info("subido %s (%s bytes)", p.name, tam)
    return subidos


def _resumen(payload: dict, adjuntos: list[AdjuntoSubido], ident: str) -> str:
    lineas = [f"Correo preparado. id: {ident}", "", f"  De:      {payload['fromAddress']}"]
    for etiqueta, clave in (("Para", "toAddress"), ("CC", "ccAddress"), ("CCO", "bccAddress")):
        if payload.get(clave):
            lineas.append(f"  {etiqueta + ':':8} {payload[clave]}")
    lineas += [
        f"  Asunto:  {payload.get('subject', '')}",
        f"  Formato: {payload.get('mailFormat', '')}",
        f"  Responder a: {payload['replyTo']}",
    ]
    if adjuntos:
        lineas.append("  Adjuntos:")
        lineas += [f"    - {a.nombre} ({tam_legible(a.bytes_)})" for a in adjuntos]
    lineas += [
        "",
        "Quedo como BORRADOR en Zoho. Nada se ha enviado.",
        f"Para mandarlo: enviar_correo con id {ident}. Para tirarlo: descartar_pendiente.",
    ]
    return "\n".join(lineas)


@SERVIDOR.tool(
    description=(
        "Prepara un correo y lo deja como BORRADOR en Zoho. NO lo envia. Sube los "
        "archivos indicados (acepta rutas de Windows). Devuelve un id que despues "
        "hay que pasarle a enviar_correo para que salga de verdad."
    )
)
async def preparar_correo(
    remitente: str,
    para: list[str],
    asunto: str,
    cuerpo: str,
    cc: list[str] | None = None,
    cco: list[str] | None = None,
    formato: str = "html",
    archivos: list[str] | None = None,
) -> str:
    # Todo lo que puede fallar sin costo va primero: alias y archivos se validan
    # antes de subir un solo byte.
    rem = resolver_remitente(remitente, await remitentes())
    validados = validar_adjuntos(archivos or [], cuenta().limite_adjunto_mb)
    subidos = await _subir_adjuntos(validados)
    payload = construir_payload(
        remitente=rem,
        para=para,
        cc=cc or [],
        cco=cco or [],
        asunto=asunto,
        cuerpo=cuerpo,
        formato=formato,
        adjuntos=subidos,
    )
    url = url_enviar(cuenta())
    # El borrador primero: si falla, no queda un pendiente que enviaria un
    # correo que nadie llego a revisar.
    r = await auth().peticion("POST", url, json={**payload, "mode": "draft"})
    borrador_id = str((r.json().get("data") or {}).get("messageId") or "")
    ident = guardar_pendiente(
        url, payload, f"para: {payload.get('toAddress', '')} | {asunto}", borrador_id
    )
    return _resumen(payload, subidos, ident)


NOMBRES_PAPELERA = ("Trash", "Papelera", "Deleted Items")

_PAPELERA: str | None = None


async def carpeta_papelera() -> str:
    global _PAPELERA
    if _PAPELERA is None:
        carpetas = await _carpetas()
        for nombre in NOMBRES_PAPELERA:
            try:
                _PAPELERA = buscar_carpeta(nombre, carpetas)
                break
            except ZohoError:
                continue
        if _PAPELERA is None:
            disponibles = ", ".join(str(c.get("folderName")) for c in carpetas)
            raise ZohoError(f"No encontre la carpeta de papelera. Hay: {disponibles}")
    return _PAPELERA


async def _borrar_borrador(message_id: str) -> str | None:
    """Quita el borrador que Zoho conserva despues de enviar.

    Se hace MOVIENDOLO A LA PAPELERA, no con un borrado duro: el borrado duro
    (DELETE /folders/{fid}/messages/{mid}) exige el scope ZohoMail.messages.DELETE,
    que no pedimos, y mover a la papelera es lo que hace una persona al borrar.
    Verificado contra la API el 2026-08-14: el modo es 'moveMessage' y el campo
    de destino se llama 'destfolderId', todo en minusculas.

    Es best-effort a proposito: cuando esto corre, el correo YA salio. Reportar
    un fallo de limpieza como fallo de envio haria pensar que hay que
    reintentar, y el correo se mandaria dos veces.

    Devuelve None si lo quito, o el motivo si no pudo.
    """
    if not message_id:
        return None
    try:
        papelera = await carpeta_papelera()
        await auth().peticion(
            "PUT",
            url_actualizar(cuenta()),
            json={
                "mode": "moveMessage",
                "messageId": [str(message_id)],
                "destfolderId": papelera,
            },
        )
        log.info("borrador %s movido a la papelera", message_id)
        return None
    except ZohoError as e:
        if "INVALID_OAUTHSCOPE" in str(e):
            return (
                "El borrador quedo en Zoho: al refresh token le faltan scopes "
                "(ZohoMail.messages.UPDATE para moverlo, ZohoMail.folders.READ "
                "para ubicar la papelera). Se puede borrar a mano desde la web."
            )
        return f"El borrador quedo en Zoho, no se pudo mover a la papelera: {e}"


def _correos_de(campo: object) -> list[str]:
    """Extrae direcciones de un campo de destinatarios de Zoho, que llega con
    entidades HTML y a veces con el literal 'Not Provided'."""
    texto = _limpio(campo)
    if not texto or texto == "Not Provided":
        return []
    salida = []
    for parte in re.split(r"[,;]", texto):
        m = _RE_CORREO_EN_FROM.search(parte)
        correo = (m.group(1) if m else parte).strip().strip("<>").strip()
        if "@" in correo and " " not in correo:
            salida.append(correo)
    return salida


@SERVIDOR.tool(
    description=(
        "Prepara una respuesta a un correo existente (referencia carpeta/mensaje) y "
        "la deja como BORRADOR. NO la envia. Devuelve un id para enviar_correo."
    )
)
async def preparar_respuesta(
    referencia: str,
    remitente: str,
    cuerpo: str,
    archivos: list[str] | None = None,
    formato: str = "html",
    responder_a_todos: bool = False,
) -> str:
    fid, mid = parse_ref(referencia)
    rem = resolver_remitente(remitente, await remitentes())
    # details, NO content: content solo trae messageId y el cuerpo, sin asunto
    # ni remitente (verificado contra la API el 2026-08-14).
    r = await auth().peticion("GET", url_detalles(cuenta(), fid, mid))
    orig = r.json().get("data", {}) or {}

    destinos = _correos_de(orig.get("fromAddress"))
    if not destinos:
        raise ZohoError(f"No pude determinar a quien responder del mensaje {referencia}")
    asunto = _limpio(orig.get("subject"))
    if not asunto.lower().startswith("re:"):
        asunto = f"Re: {asunto}"

    copia: list[str] = []
    if responder_a_todos:
        propias = {r.correo.lower() for r in await remitentes()}
        copia = [
            c
            for c in _correos_de(orig.get("toAddress")) + _correos_de(orig.get("ccAddress"))
            if c.lower() not in propias and c.lower() not in {d.lower() for d in destinos}
        ]

    validados = validar_adjuntos(archivos or [], cuenta().limite_adjunto_mb)
    subidos = await _subir_adjuntos(validados)
    payload = construir_payload(
        remitente=rem,
        para=destinos,
        cc=copia,
        cco=[],
        asunto=asunto,
        cuerpo=cuerpo,
        formato=formato,
        adjuntos=subidos,
    )
    payload["action"] = "replyall" if responder_a_todos else "reply"

    url = url_responder(cuenta(), mid)
    r = await auth().peticion("POST", url, json={**payload, "mode": "draft"})
    borrador_id = str((r.json().get("data") or {}).get("messageId") or "")
    ident = guardar_pendiente(
        url, payload, f"respuesta a: {destinos[0]} | {asunto}", borrador_id
    )
    return _resumen(payload, subidos, ident)


@SERVIDOR.tool(
    description=(
        "Envia DE VERDAD un correo previamente preparado, por su id. Esta accion no "
        "se puede deshacer. No vuelve a subir los adjuntos: reusa los que ya estan "
        "en Zoho."
    )
)
async def enviar_correo(id_pendiente: str) -> str:
    p = leer_pendiente(id_pendiente, cuenta())
    r = await auth().peticion("POST", p["url"], json=p["payload"])
    datos = r.json().get("data", {}) or {}
    # Se borra despues de que la API confirmo: si el envio falla, el pendiente
    # sigue ahi para reintentar sin volver a subir nada.
    borrar_pendiente(id_pendiente)
    mid = datos.get("messageId", "(sin id)")
    log.info("correo %s enviado, messageId %s", id_pendiente, mid)

    # Limpieza del borrador. Va DESPUES de borrar el pendiente y su fallo nunca
    # se propaga: el correo ya salio.
    aviso = await _borrar_borrador(p.get("borrador_id", ""))

    salida = (
        f"Enviado. messageId: {mid}\n"
        f"  Para: {p['payload'].get('toAddress')}\n"
        f"  Asunto: {p['payload'].get('subject')}"
    )
    return salida + (f"\n\nNota: {aviso}" if aviso else "")


@SERVIDOR.tool(
    description=(
        "Lista los correos preparados que siguen esperando confirmacion, con su "
        "id. Util si se perdio el id de la conversacion: los pendientes viven en "
        "disco y sobreviven a un reinicio."
    )
)
async def listar_pendientes() -> str:
    return listar_pendientes_texto(cuenta())


@SERVIDOR.tool(description="Tira a la basura un correo preparado que ya no se va a enviar.")
async def descartar_pendiente(id_pendiente: str) -> str:
    p = leer_pendiente(id_pendiente, cuenta())  # falla claro si no existe o es ajeno
    borrar_pendiente(id_pendiente)
    aviso = await _borrar_borrador(p.get("borrador_id", ""))
    if aviso:
        return f"Pendiente {id_pendiente} descartado. {aviso}"
    return f"Pendiente {id_pendiente} descartado y su borrador borrado de Zoho."


# --- 9. Arranque ----------------------------------------------------------


def main() -> None:
    log.info("servidor zoho-mail iniciando")
    try:
        purgar_pendientes()
    except OSError as e:  # que un fallo de purga no impida arrancar
        log.warning("no se pudo purgar pendientes: %s", e)
    SERVIDOR.run()


if __name__ == "__main__":
    main()
