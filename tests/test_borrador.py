"""Limpieza del borrador que queda tras enviar.

El patron preparar->confirmar crea un borrador y despues manda un mensaje
aparte, asi que Zoho se queda con los DOS. Sin esta limpieza, cada correo
enviado deja un borrador huerfano acumulandose (observado el 2026-08-14).
"""

import json as _json

import httpx
import pytest
import respx

import zoho_mail_mcp as z

AID = "1000000000000000002"
CUENTA = z.Cuenta(
    nombre="prueba",
    client_id="cid",
    client_secret="cs",
    refresh_token="rt",
    account_id=AID,
    limite_adjunto_mb=20,
)
URL_TOKEN = "https://accounts.zoho.com/oauth/v2/token"


@pytest.fixture(autouse=True)
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(z, "DIR_PENDIENTES", tmp_path / "pendientes")
    cuenta = CUENTA
    cliente = httpx.AsyncClient()
    monkeypatch.setattr(z, "_CUENTA", cuenta)
    monkeypatch.setattr(z, "_CLIENTE", cliente)
    monkeypatch.setattr(z, "_AUTH", z.Auth(cuenta, cliente))
    monkeypatch.setattr(
        z, "_REMITENTES", [z.Remitente("remitente@ejemplo.com", "Remitente Ejemplo")]
    )
    monkeypatch.setattr(z, "_PAPELERA", None)  # cache global, no debe cruzarse
    return tmp_path


TRASH = "1000000000000000024"


def montar(borrado_ok=True):
    respx.post(URL_TOKEN).mock(
        return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
    )
    # La papelera se ubica por nombre; su id no se puede clavar en el codigo.
    respx.get(z.url_carpetas(CUENTA)).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"folderId": "1000000000000000016", "folderName": "Drafts"},
                    {"folderId": TRASH, "folderName": "Trash"},
                ]
            },
        )
    )
    envio = respx.post(z.url_enviar(CUENTA)).mock(
        side_effect=[
            # 1. creacion del borrador: devuelve SU messageId
            httpx.Response(200, json={"data": {"mode": "draft", "messageId": "DRAFT-1"}}),
            # 2. envio real
            httpx.Response(200, json={"data": {"messageId": "MSG-1"}}),
        ]
    )
    if borrado_ok:
        borrado = respx.put(z.url_actualizar(CUENTA)).mock(
            return_value=httpx.Response(200, json={"status": {"code": 200}})
        )
    else:
        borrado = respx.put(z.url_actualizar(CUENTA)).mock(
            return_value=httpx.Response(
                401, text='[2, {"errorCode":"INVALID_OAUTHSCOPE","status":"401"}]'
            )
        )
    return envio, borrado


async def preparar():
    salida = await z.preparar_correo(
        remitente="remitente@ejemplo.com", para=["c@x.com"], asunto="s", cuerpo="c"
    )
    return salida.split("id: ")[1].split()[0]


@respx.mock
async def test_el_id_del_borrador_se_guarda_en_el_pendiente():
    montar()
    ident = await preparar()
    assert z.leer_pendiente(ident, CUENTA)["borrador_id"] == "DRAFT-1"


@respx.mock
async def test_al_enviar_el_borrador_se_va_a_la_papelera():
    """El borrado duro exige ZohoMail.messages.DELETE, que no pedimos. Mover a
    la papelera es lo que hace una persona al borrar, y basta con messages.UPDATE."""
    _, borrado = montar()
    ident = await preparar()
    salida = await z.enviar_correo(ident)

    assert borrado.call_count == 1
    cuerpo = _json.loads(borrado.calls[0].request.content)
    assert cuerpo["mode"] == "moveMessage"
    assert cuerpo["messageId"] == ["DRAFT-1"]
    # El campo va en minusculas. 'destFolderId' o 'folderId' fallan (verificado
    # contra la API el 2026-08-14).
    assert cuerpo["destfolderId"] == TRASH
    assert "MSG-1" in salida


@respx.mock
async def test_la_papelera_se_busca_una_sola_vez():
    respx.post(URL_TOKEN).mock(
        return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
    )
    carpetas = respx.get(z.url_carpetas(CUENTA)).mock(
        return_value=httpx.Response(
            200, json={"data": [{"folderId": TRASH, "folderName": "Trash"}]}
        )
    )
    for _ in range(3):
        assert await z.carpeta_papelera() == TRASH
    assert carpetas.call_count == 1, "el id de la papelera debe cachearse"


@respx.mock
async def test_la_papelera_se_busca_por_nombre_no_por_id_fijo():
    """Otra cuenta puede tener otros ids, o la carpeta en español."""
    respx.post(URL_TOKEN).mock(
        return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
    )
    respx.get(z.url_carpetas(CUENTA)).mock(
        return_value=httpx.Response(
            200, json={"data": [{"folderId": "999", "folderName": "Papelera"}]}
        )
    )
    assert await z.carpeta_papelera() == "999"


@respx.mock
async def test_si_no_se_puede_borrar_el_envio_NO_falla():
    """El correo ya salio. Un fallo de limpieza no puede reportarse como error
    de envio: haria pensar que hay que reintentar, y se mandaria dos veces."""
    _, borrado = montar(borrado_ok=False)
    ident = await preparar()
    salida = await z.enviar_correo(ident)

    assert "MSG-1" in salida, "el envio debe reportarse como exitoso"
    assert "scope" in salida.lower(), "pero debe avisar por que quedo el borrador"
    assert borrado.call_count == 1


@respx.mock
async def test_descartar_tambien_borra_el_borrador():
    _, borrado = montar()
    ident = await preparar()
    salida = await z.descartar_pendiente(ident)
    assert borrado.call_count == 1
    assert "borrado" in salida.lower() or "elimin" in salida.lower()


@respx.mock
async def test_un_pendiente_viejo_sin_borrador_id_no_truena():
    """Los pendientes guardados antes de esta version no traen el campo.
    Deben enviarse igual, sin intentar borrar un borrador que no se conoce."""
    _, borrado = montar()
    ident = z.guardar_pendiente(z.url_enviar(CUENTA), {"toAddress": "c@x.com"}, "viejo")

    salida = await z.enviar_correo(ident)

    assert "Enviado" in salida
    assert "Nota:" not in salida, "no debe avisar de un borrador que nunca hubo"
    assert borrado.call_count == 0, "sin id no hay nada que borrar"
