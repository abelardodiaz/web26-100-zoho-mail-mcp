"""Secuencia completa preparar -> confirmar contra un doble de la API.

Aqui vive la prueba que justifica que exista pendientes/:
test_confirmar_no_vuelve_a_subir_adjuntos.
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
    """Doble completo: cuenta falsa, cliente propio, pendientes en tmp."""
    monkeypatch.setattr(z, "DIR_PENDIENTES", tmp_path / "pendientes")
    cuenta = CUENTA
    cliente = httpx.AsyncClient()
    monkeypatch.setattr(z, "_CUENTA", cuenta)
    monkeypatch.setattr(z, "_CLIENTE", cliente)
    monkeypatch.setattr(z, "_AUTH", z.Auth(cuenta, cliente))
    monkeypatch.setattr(
        z, "_REMITENTES", [z.Remitente("remitente@ejemplo.com", "Remitente Ejemplo")]
    )
    monkeypatch.setattr(z, "_PAPELERA", "1000000000000000024")  # evita el GET de carpetas
    return tmp_path


def rutas_falsas():
    """Devuelve (ruta_subida, ruta_envio) ya montadas en respx."""
    respx.post(URL_TOKEN).mock(
        return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
    )
    subida = respx.post(z.url_subir(CUENTA)).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": {"code": 200},
                "data": [
                    {
                        "attachmentSize": "1234",
                        "storeName": "store-1",
                        "attachmentName": "doc.pdf",
                        "attachmentPath": "/api/att/1",
                        "url": "https://x",
                    }
                ],
            },
        )
    )
    envio = respx.post(z.url_enviar(CUENTA)).mock(
        return_value=httpx.Response(
            200, json={"status": {"code": 200}, "data": {"messageId": "MSG-1"}}
        )
    )
    # Limpieza del borrador tras enviar (ver test_borrador.py)
    respx.put(z.url_actualizar(CUENTA)).mock(
        return_value=httpx.Response(200, json={"status": {"code": 200}})
    )
    return subida, envio


def id_de(salida: str) -> str:
    return salida.split("id: ")[1].split()[0]


@respx.mock
async def test_preparar_sube_el_adjunto_y_crea_borrador(entorno):
    subida, envio = rutas_falsas()
    archivo = entorno / "doc.pdf"
    archivo.write_bytes(b"%PDF-fake")

    salida = await z.preparar_correo(
        remitente="remitente@ejemplo.com",
        para=["cliente@ejemplo.com"],
        asunto="Propuesta",
        cuerpo="<p>Va adjunta</p>",
        archivos=[str(archivo)],
    )

    assert subida.call_count == 1
    assert envio.call_count == 1
    cuerpo = _json.loads(envio.calls[0].request.content)
    assert cuerpo["mode"] == "draft"
    assert cuerpo["attachments"][0]["storeName"] == "store-1"
    assert cuerpo["replyTo"] == "remitente@ejemplo.com"
    assert "doc.pdf" in salida
    assert "BORRADOR" in salida, "el resumen debe dejar claro que no se envio"


@respx.mock
async def test_confirmar_no_vuelve_a_subir_adjuntos(entorno):
    """La prueba mas importante del archivo. Es la razon de que exista pendientes/."""
    subida, envio = rutas_falsas()
    archivo = entorno / "doc.pdf"
    archivo.write_bytes(b"%PDF-fake")

    salida = await z.preparar_correo(
        remitente="remitente@ejemplo.com",
        para=["cliente@ejemplo.com"],
        asunto="Propuesta",
        cuerpo="<p>x</p>",
        archivos=[str(archivo)],
    )
    resultado = await z.enviar_correo(id_de(salida))

    assert subida.call_count == 1, "confirmar volvio a subir el adjunto"
    assert envio.call_count == 2
    segundo = _json.loads(envio.calls[1].request.content)
    assert "mode" not in segundo, "el envio real no debe llevar mode=draft"
    assert segundo["attachments"][0]["storeName"] == "store-1"
    assert "MSG-1" in resultado


@respx.mock
async def test_el_correo_enviado_es_identico_al_del_borrador(entorno):
    """Si el payload cambiara entre borrador y envio, revisar el borrador no
    probaria nada sobre lo que de verdad sale."""
    _, envio = rutas_falsas()
    salida = await z.preparar_correo(
        remitente="remitente@ejemplo.com",
        para=["c@x.com"],
        cc=["jefe@x.com"],
        asunto="Cotizacion",
        cuerpo="<p>hola</p>",
    )
    await z.enviar_correo(id_de(salida))

    borrador = _json.loads(envio.calls[0].request.content)
    enviado = _json.loads(envio.calls[1].request.content)
    del borrador["mode"]
    assert borrador == enviado


@respx.mock
async def test_enviar_borra_el_pendiente(entorno):
    rutas_falsas()
    salida = await z.preparar_correo(
        remitente="remitente@ejemplo.com", para=["c@x.com"], asunto="s", cuerpo="c"
    )
    ident = id_de(salida)
    await z.enviar_correo(ident)
    with pytest.raises(z.ZohoError, match="No hay un pendiente"):
        z.leer_pendiente(ident)


@respx.mock
async def test_no_se_puede_enviar_dos_veces(entorno):
    """Reenviar por accidente es el peor error posible de esta herramienta."""
    _, envio = rutas_falsas()
    salida = await z.preparar_correo(
        remitente="remitente@ejemplo.com", para=["c@x.com"], asunto="s", cuerpo="c"
    )
    ident = id_de(salida)
    await z.enviar_correo(ident)
    with pytest.raises(z.ZohoError, match="No hay un pendiente"):
        await z.enviar_correo(ident)
    assert envio.call_count == 2, "el segundo envio no debe llegar a la red"


@respx.mock
async def test_remitente_invalido_no_sube_nada(entorno):
    subida, envio = rutas_falsas()
    archivo = entorno / "doc.pdf"
    archivo.write_bytes(b"%PDF-fake")
    with pytest.raises(z.ZohoError, match="alias confirmado"):
        await z.preparar_correo(
            remitente="ajeno@otrodominio.com",
            para=["c@x.com"],
            asunto="s",
            cuerpo="c",
            archivos=[str(archivo)],
        )
    assert subida.call_count == 0
    assert envio.call_count == 0


@respx.mock
async def test_archivo_inexistente_no_sube_nada(entorno):
    subida, envio = rutas_falsas()
    with pytest.raises(z.ZohoError, match="No existe"):
        await z.preparar_correo(
            remitente="remitente@ejemplo.com",
            para=["c@x.com"],
            asunto="s",
            cuerpo="c",
            archivos=[str(entorno / "fantasma.pdf")],
        )
    assert subida.call_count == 0
    assert envio.call_count == 0


@respx.mock
async def test_fallo_a_mitad_de_subida_aborta_sin_dejar_borrador(entorno):
    respx.post(URL_TOKEN).mock(
        return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
    )
    respx.post(z.url_subir(CUENTA)).mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "attachmentName": "a.pdf",
                            "attachmentPath": "/p/1",
                            "storeName": "s1",
                            "attachmentSize": "10",
                        }
                    ]
                },
            ),
            httpx.Response(500, text="boom"),
        ]
    )
    envio = respx.post(z.url_enviar(CUENTA)).mock(return_value=httpx.Response(200, json={}))
    (entorno / "a.pdf").write_bytes(b"aaa")
    (entorno / "b.pdf").write_bytes(b"bbb")

    with pytest.raises(z.ZohoError, match="b.pdf"):
        await z.preparar_correo(
            remitente="remitente@ejemplo.com",
            para=["c@x.com"],
            asunto="s",
            cuerpo="c",
            archivos=[str(entorno / "a.pdf"), str(entorno / "b.pdf")],
        )
    assert envio.call_count == 0, "no debe quedar un borrador a medias"


@respx.mock
async def test_si_falla_el_borrador_no_queda_pendiente(entorno):
    """Un pendiente sin borrador enviaria un correo que nadie reviso."""
    respx.post(URL_TOKEN).mock(
        return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
    )
    respx.post(z.url_enviar(CUENTA)).mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(z.ZohoError):
        await z.preparar_correo(
            remitente="remitente@ejemplo.com", para=["c@x.com"], asunto="s", cuerpo="c"
        )
    assert "Sin correos" in z.listar_pendientes_texto()


@respx.mock
async def test_descartar_elimina_el_pendiente(entorno):
    rutas_falsas()
    salida = await z.preparar_correo(
        remitente="remitente@ejemplo.com", para=["c@x.com"], asunto="s", cuerpo="c"
    )
    ident = id_de(salida)
    assert "descartado" in (await z.descartar_pendiente(ident)).lower()
    with pytest.raises(z.ZohoError):
        z.leer_pendiente(ident)


# --- respuestas ------------------------------------------------------------


def montar_original(subject="Cotizacion", de="cliente@ejemplo.com", para=None, cc=None):
    """El ORIGINAL se lee de /details, no de /content: content solo trae
    messageId y el cuerpo (verificado contra la API el 2026-08-14)."""
    respx.post(URL_TOKEN).mock(
        return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
    )
    respx.get(z.url_detalles(CUENTA, "77", "MSG-ORIG")).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "subject": subject,
                    "fromAddress": de,
                    "toAddress": para or "&lt;remitente@ejemplo.com&gt;",
                    "ccAddress": cc or "Not Provided",
                    "messageId": "MSG-ORIG",
                }
            },
        )
    )
    respx.put(z.url_actualizar(CUENTA)).mock(
        return_value=httpx.Response(200, json={"status": {"code": 200}})
    )
    return respx.post(z.url_responder(CUENTA, "MSG-ORIG")).mock(
        return_value=httpx.Response(200, json={"data": {"messageId": "MSG-2"}})
    )


@respx.mock
async def test_preparar_respuesta_usa_el_endpoint_del_mensaje(entorno):
    respuesta = montar_original()

    salida = await z.preparar_respuesta(
        referencia="77/MSG-ORIG",
        remitente="remitente@ejemplo.com",
        cuerpo="<p>Va la respuesta</p>",
    )

    cuerpo = _json.loads(respuesta.calls[0].request.content)
    assert cuerpo["action"] == "reply"
    assert cuerpo["mode"] == "draft"
    assert cuerpo["toAddress"] == "cliente@ejemplo.com"
    assert cuerpo["subject"].startswith("Re:")
    assert cuerpo["replyTo"] == "remitente@ejemplo.com"

    await z.enviar_correo(id_de(salida))
    assert respuesta.call_count == 2
    assert "mode" not in _json.loads(respuesta.calls[1].request.content)


@respx.mock
async def test_no_se_apila_re_sobre_re(entorno):
    respuesta = montar_original(subject="Re: Cotizacion")
    await z.preparar_respuesta(
        referencia="77/MSG-ORIG", remitente="remitente@ejemplo.com", cuerpo="x"
    )
    assert _json.loads(respuesta.calls[0].request.content)["subject"] == "Re: Cotizacion"


@respx.mock
async def test_el_remitente_del_original_llega_desescapado(entorno):
    """details devuelve las direcciones con entidades HTML."""
    respuesta = montar_original(de="&quot;Jose&quot; &lt;jose@ejemplo.com&gt;")
    await z.preparar_respuesta(
        referencia="77/MSG-ORIG", remitente="remitente@ejemplo.com", cuerpo="x"
    )
    assert _json.loads(respuesta.calls[0].request.content)["toAddress"] == "jose@ejemplo.com"


@respx.mock
async def test_responder_a_todos_suma_los_demas_en_copia(entorno):
    respuesta = montar_original(
        para="&lt;remitente@ejemplo.com&gt;, &lt;colega@ejemplo.com&gt;",
        cc="&lt;jefe@ejemplo.com&gt;",
    )
    await z.preparar_respuesta(
        referencia="77/MSG-ORIG",
        remitente="remitente@ejemplo.com",
        cuerpo="x",
        responder_a_todos=True,
    )
    cuerpo = _json.loads(respuesta.calls[0].request.content)
    assert cuerpo["action"] == "replyall"
    assert cuerpo["toAddress"] == "cliente@ejemplo.com"
    copia = cuerpo["ccAddress"]
    assert "colega@ejemplo.com" in copia and "jefe@ejemplo.com" in copia
    assert "remitente@ejemplo.com" not in copia, "no hay que copiarse a uno mismo"


@respx.mock
async def test_responder_sin_saber_a_quien_falla(entorno):
    montar_original(de="")
    with pytest.raises(z.ZohoError, match="a quien responder"):
        await z.preparar_respuesta(
            referencia="77/MSG-ORIG", remitente="remitente@ejemplo.com", cuerpo="x"
        )


@respx.mock
async def test_el_pendiente_aparece_en_el_listado(entorno):
    rutas_falsas()
    salida = await z.preparar_correo(
        remitente="remitente@ejemplo.com",
        para=["cliente@ejemplo.com"],
        asunto="Cotizacion agosto",
        cuerpo="c",
    )
    listado = await z.listar_pendientes()
    assert id_de(salida) in listado
    assert "Cotizacion agosto" in listado
