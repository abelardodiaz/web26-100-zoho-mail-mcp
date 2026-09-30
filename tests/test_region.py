"""Centro de datos por cuenta.

Una cuenta Zoho solo se autentica contra su propio centro de datos: un Self
Client de api-console.zoho.eu no canjea tokens en accounts.zoho.com. Pedido por
web26-602 el 2026-09-30 para una cuenta alojada en EU.
"""

import json

import httpx
import pytest
import respx

import zoho_mail_mcp as z


def escribir_cuenta(tmp_path, **extra) -> str:
    datos = {
        "nombre": "prueba",
        "client_id": "cid",
        "client_secret": "cs",
        "refresh_token": "rt",
        "account_id": "123",
        **extra,
    }
    p = tmp_path / "cuenta.json"
    p.write_text(json.dumps(datos), encoding="utf-8")
    return str(p)


def test_sin_region_la_cuenta_sigue_en_com(tmp_path):
    """Compatibilidad: los JSON que ya existen no tienen el campo."""
    c = z.cargar_cuenta(escribir_cuenta(tmp_path))
    assert c.region == "com"
    assert c.api == "https://mail.zoho.com/api"
    assert c.url_token == "https://accounts.zoho.com/oauth/v2/token"


def test_region_eu_deriva_todos_los_endpoints(tmp_path):
    c = z.cargar_cuenta(escribir_cuenta(tmp_path, region="eu"))
    assert c.api == "https://mail.zoho.eu/api"
    assert c.url_token == "https://accounts.zoho.eu/oauth/v2/token"
    assert c.url_cuentas == "https://mail.zoho.eu/api/accounts"
    assert c.consola == "api-console.zoho.eu"
    assert z.url_enviar(c) == "https://mail.zoho.eu/api/accounts/123/messages"


def test_region_se_normaliza(tmp_path):
    c = z.cargar_cuenta(escribir_cuenta(tmp_path, region=" EU "))
    assert c.region == "eu"


def test_canada_no_sigue_el_patron_zoho_punto_region(tmp_path):
    """Por esto la tabla es explicita y no f'zoho.{region}'."""
    c = z.cargar_cuenta(escribir_cuenta(tmp_path, region="ca"))
    assert c.url_token == "https://accounts.zohocloud.ca/oauth/v2/token"


def test_region_desconocida_se_rechaza_en_vez_de_caer_a_com(tmp_path):
    with pytest.raises(z.ZohoError) as e:
        z.cargar_cuenta(escribir_cuenta(tmp_path, region="europa"))
    assert "europa" in str(e.value) and "eu" in str(e.value)


def test_region_no_permite_inyectar_un_host(tmp_path):
    """El client_secret viaja a url_token: la region nunca puede apuntar fuera de Zoho."""
    with pytest.raises(z.ZohoError):
        z.cargar_cuenta(escribir_cuenta(tmp_path, region="eu.atacante.com/x?"))


def cuenta_eu() -> "z.Cuenta":
    return z.Cuenta(
        nombre="prueba",
        client_id="cid",
        client_secret="cs",
        refresh_token="rt",
        account_id="123",
        region="eu",
    )


@respx.mock
async def test_cuenta_eu_pide_token_y_datos_en_eu():
    token = respx.post("https://accounts.zoho.eu/oauth/v2/token").mock(
        return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
    )
    datos = respx.get("https://mail.zoho.eu/api/accounts").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    c = cuenta_eu()
    async with httpx.AsyncClient() as cliente:
        await z.Auth(c, cliente).peticion("GET", c.url_cuentas)
    assert token.call_count == 1
    assert datos.call_count == 1


@respx.mock
async def test_refresh_rechazado_en_eu_manda_a_la_consola_eu():
    respx.post("https://accounts.zoho.eu/oauth/v2/token").mock(
        return_value=httpx.Response(200, json={"error": "invalid_code"})
    )
    async with httpx.AsyncClient() as cliente:
        with pytest.raises(z.ErrorAuth) as e:
            await z.Auth(cuenta_eu(), cliente).token()
    assert "api-console.zoho.eu" in str(e.value)
    assert "zoho.com" not in str(e.value)
    assert "scopes ZohoMail.messages.CREATE" in str(e.value)
