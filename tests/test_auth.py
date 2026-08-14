import httpx
import pytest
import respx

import zoho_mail_mcp as z


def cuenta_falsa() -> "z.Cuenta":
    return z.Cuenta(
        nombre="prueba",
        client_id="cid",
        client_secret="secreto",
        refresh_token="rt",
        account_id="123",
        limite_adjunto_mb=20,
    )


@respx.mock
async def test_token_se_pide_una_vez_y_se_cachea():
    ruta = respx.post(z.URL_TOKEN).mock(
        return_value=httpx.Response(200, json={"access_token": "T1", "expires_in": 3600})
    )
    async with httpx.AsyncClient() as cliente:
        auth = z.Auth(cuenta_falsa(), cliente)
        assert await auth.token() == "T1"
        assert await auth.token() == "T1"
    assert ruta.call_count == 1


@respx.mock
async def test_401_renueva_una_vez_y_reintenta():
    respx.post(z.URL_TOKEN).mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "VIEJO", "expires_in": 3600}),
            httpx.Response(200, json={"access_token": "NUEVO", "expires_in": 3600}),
        ]
    )
    llamadas = respx.get("https://mail.zoho.com/api/accounts").mock(
        side_effect=[
            httpx.Response(401, text="expired"),
            httpx.Response(200, json={"data": []}),
        ]
    )
    async with httpx.AsyncClient() as cliente:
        auth = z.Auth(cuenta_falsa(), cliente)
        r = await auth.peticion("GET", z.URL_CUENTAS)
    assert r.status_code == 200
    assert llamadas.call_count == 2
    assert llamadas.calls[1].request.headers["Authorization"] == "Zoho-oauthtoken NUEVO"


@respx.mock
async def test_segundo_401_se_rinde():
    respx.post(z.URL_TOKEN).mock(
        return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
    )
    respx.get("https://mail.zoho.com/api/accounts").mock(
        return_value=httpx.Response(401, text="expired")
    )
    async with httpx.AsyncClient() as cliente:
        auth = z.Auth(cuenta_falsa(), cliente)
        with pytest.raises(z.ZohoError, match="401"):
            await auth.peticion("GET", z.URL_CUENTAS)


@respx.mock
async def test_refresh_token_invalido_no_se_reintenta_jamas():
    ruta = respx.post(z.URL_TOKEN).mock(
        return_value=httpx.Response(200, json={"error": "invalid_grant"})
    )
    async with httpx.AsyncClient() as cliente:
        auth = z.Auth(cuenta_falsa(), cliente)
        for _ in range(3):
            with pytest.raises(z.ErrorAuth, match="api-console"):
                await auth.token()
    assert ruta.call_count == 1


def test_alias_se_extraen_de_send_mail_details():
    datos = {
        "accountId": "123",
        "sendMailDetails": [
            {"fromAddress": "remitente@ejemplo.com", "displayName": "Remitente Ejemplo"},
            {"fromAddress": "otro@ejemplo.com", "displayName": ""},
        ],
    }
    remitentes = z.extraer_remitentes(datos)
    assert remitentes[0] == z.Remitente("remitente@ejemplo.com", "Remitente Ejemplo")
    assert remitentes[1].nombre == ""


@respx.mock
async def test_scope_invalido_no_gasta_una_renovacion_de_token():
    """Observado el 2026-08-14 contra /folders: un 401 por scope faltante
    disparaba renovar el token y reintentar, y el reintento no puede arreglarlo."""
    token = respx.post(z.URL_TOKEN).mock(
        return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
    )
    llamadas = respx.get("https://mail.zoho.com/api/accounts").mock(
        return_value=httpx.Response(
            401, text='[2, {"errorCode":"INVALID_OAUTHSCOPE","status":"401"}]'
        )
    )
    async with httpx.AsyncClient() as cliente:
        auth = z.Auth(cuenta_falsa(), cliente)
        with pytest.raises(z.ZohoError, match="INVALID_OAUTHSCOPE"):
            await auth.peticion("GET", z.URL_CUENTAS)
    assert llamadas.call_count == 1, "no debe reintentar"
    assert token.call_count == 1, "no debe renovar el token"


async def test_la_herramienta_info_cuenta_esta_registrada():
    nombres = {t.name for t in await z.SERVIDOR.list_tools()}
    assert "info_cuenta" in nombres
