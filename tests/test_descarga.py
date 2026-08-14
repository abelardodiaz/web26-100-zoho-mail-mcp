"""Descarga de adjuntos contra un doble de la API."""

import httpx
import pytest
import respx

import zoho_mail_mcp as z

CUENTA = z.Cuenta(
    nombre="prueba",
    client_id="cid",
    client_secret="secreto",
    refresh_token="rt",
    account_id="999",
    limite_adjunto_mb=20,
)

REF = "77/1234"
URL_ADJUNTO = z.url_bajar_adjunto("999", "77", "1234", "abc")


@pytest.fixture
def servidor_falso(monkeypatch):
    """Inyecta cuenta y auth ya construidos para no pasar por cargar_cuenta()."""
    cliente = httpx.AsyncClient()
    auth = z.Auth(CUENTA, cliente)
    monkeypatch.setattr(z, "_CUENTA", CUENTA)
    monkeypatch.setattr(z, "_CLIENTE", cliente)
    monkeypatch.setattr(z, "_AUTH", auth)
    respx.post(z.URL_TOKEN).mock(
        return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
    )
    return auth


@respx.mock
async def test_descarga_escribe_los_bytes_tal_cual(servidor_falso, tmp_path):
    contenido = bytes(range(256)) * 40  # binario con bytes no imprimibles
    respx.get(URL_ADJUNTO).mock(return_value=httpx.Response(200, content=contenido))
    destino = tmp_path / "bajado.bin"

    salida = await z.descargar_adjunto(REF, "abc", str(destino))

    assert destino.read_bytes() == contenido, "el archivo no debe corromperse"
    assert str(destino) in salida


@respx.mock
async def test_no_toca_la_red_si_el_destino_es_invalido(servidor_falso, tmp_path):
    """Bajar 20 MB para descubrir que el directorio no existe es tiempo tirado."""
    ruta = respx.get(URL_ADJUNTO).mock(return_value=httpx.Response(200, content=b"x"))

    with pytest.raises(z.ZohoError, match="no existe"):
        await z.descargar_adjunto(REF, "abc", str(tmp_path / "sin-crear" / "a.bin"))

    assert ruta.call_count == 0


@respx.mock
async def test_no_pisa_un_archivo_existente(servidor_falso, tmp_path):
    respx.get(URL_ADJUNTO).mock(return_value=httpx.Response(200, content=b"nuevo"))
    destino = tmp_path / "a.bin"
    destino.write_bytes(b"viejo")

    with pytest.raises(z.ZohoError, match="[Yy]a existe"):
        await z.descargar_adjunto(REF, "abc", str(destino))
    assert destino.read_bytes() == b"viejo"

    await z.descargar_adjunto(REF, "abc", str(destino), sobrescribir=True)
    assert destino.read_bytes() == b"nuevo"


@respx.mock
async def test_respuesta_vacia_no_deja_archivo_basura(servidor_falso, tmp_path):
    respx.get(URL_ADJUNTO).mock(return_value=httpx.Response(200, content=b""))
    destino = tmp_path / "vacio.bin"

    with pytest.raises(z.ZohoError, match="vacio"):
        await z.descargar_adjunto(REF, "abc", str(destino))

    assert not destino.exists(), "no debe quedar un archivo de 0 bytes"


@respx.mock
async def test_referencia_mala_falla_antes_de_la_red(servidor_falso, tmp_path):
    ruta = respx.get(URL_ADJUNTO).mock(return_value=httpx.Response(200, content=b"x"))

    with pytest.raises(z.ZohoError, match="carpeta/mensaje"):
        await z.descargar_adjunto("1234", "abc", str(tmp_path / "a.bin"))

    assert ruta.call_count == 0
