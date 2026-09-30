"""Pendientes en disco.

Van a disco y no a memoria a proposito: si Claude Code reinicia entre preparar
y confirmar, el correo (y los adjuntos ya subidos a Zoho) no se pierden.
"""

import os
import time

import pytest

import zoho_mail_mcp as z

CUENTA = z.Cuenta(
    nombre="prueba",
    client_id="cid",
    client_secret="cs",
    refresh_token="rt",
    account_id="111",
)
URL = z.url_enviar(CUENTA)


@pytest.fixture(autouse=True)
def dir_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(z, "DIR_PENDIENTES", tmp_path / "pendientes")
    return tmp_path / "pendientes"


def test_guardar_y_leer_ida_y_vuelta():
    ident = z.guardar_pendiente(URL, {"subject": "hola"}, "resumen")
    p = z.leer_pendiente(ident, CUENTA)
    assert p["payload"] == {"subject": "hola"}
    assert p["url"] == URL
    assert p["resumen"] == "resumen"


def test_el_archivo_queda_con_permisos_600(dir_temporal):
    ident = z.guardar_pendiente(URL, {}, "r")
    modo = (dir_temporal / f"{ident}.json").stat().st_mode & 0o777
    assert modo == 0o600


def test_no_quedan_archivos_temporales(dir_temporal):
    z.guardar_pendiente(URL, {}, "r")
    assert list(dir_temporal.glob("*.tmp")) == []


def test_dos_pendientes_seguidos_no_colisionan():
    a = z.guardar_pendiente(URL, {"n": 1}, "a")
    b = z.guardar_pendiente(URL, {"n": 2}, "b")
    assert a != b
    assert z.leer_pendiente(a, CUENTA)["payload"] == {"n": 1}
    assert z.leer_pendiente(b, CUENTA)["payload"] == {"n": 2}


def test_el_contenido_sobrevive_acentos(dir_temporal):
    ident = z.guardar_pendiente(URL, {"subject": "Cotización año 2026"}, "r")
    crudo = (dir_temporal / f"{ident}.json").read_text(encoding="utf-8")
    assert "Cotización año 2026" in crudo
    assert z.leer_pendiente(ident, CUENTA)["payload"]["subject"] == "Cotización año 2026"


def test_pendiente_inexistente_falla_claro():
    with pytest.raises(z.ZohoError, match="No hay un pendiente"):
        z.leer_pendiente("20260805120000-abcdef", CUENTA)


def test_pendiente_corrupto_falla_claro(dir_temporal):
    dir_temporal.mkdir(parents=True, exist_ok=True)
    (dir_temporal / "roto.json").write_text("{no es json", encoding="utf-8")
    with pytest.raises(z.ZohoError, match="ilegible"):
        z.leer_pendiente("roto", CUENTA)


def test_pendiente_sin_los_campos_esperados_falla(dir_temporal):
    dir_temporal.mkdir(parents=True, exist_ok=True)
    (dir_temporal / "incompleto.json").write_text('{"resumen": "x"}', encoding="utf-8")
    with pytest.raises(z.ZohoError, match="ilegible"):
        z.leer_pendiente("incompleto", CUENTA)


def test_id_con_separadores_de_ruta_se_rechaza():
    """El id llega desde afuera: no debe poder apuntar fuera del directorio."""
    for malo in ("../../etc/passwd", "a/b", r"a\b", "/etc/passwd"):
        with pytest.raises(z.ZohoError, match="identificador"):
            z.leer_pendiente(malo, CUENTA)


def test_borrar_quita_el_archivo(dir_temporal):
    ident = z.guardar_pendiente(URL, {}, "r")
    z.borrar_pendiente(ident)
    assert not (dir_temporal / f"{ident}.json").exists()


def test_borrar_dos_veces_no_truena():
    ident = z.guardar_pendiente(URL, {}, "r")
    z.borrar_pendiente(ident)
    z.borrar_pendiente(ident)


def test_purga_borra_viejos_y_respeta_recientes(dir_temporal):
    viejo = z.guardar_pendiente(URL, {}, "viejo")
    nuevo = z.guardar_pendiente(URL, {}, "nuevo")
    hace_ocho_dias = time.time() - 8 * 86400
    os.utime(dir_temporal / f"{viejo}.json", (hace_ocho_dias, hace_ocho_dias))
    assert z.purgar_pendientes() == 1
    assert not (dir_temporal / f"{viejo}.json").exists()
    assert (dir_temporal / f"{nuevo}.json").exists()


def test_purga_sin_directorio_no_truena(tmp_path, monkeypatch):
    monkeypatch.setattr(z, "DIR_PENDIENTES", tmp_path / "nada")
    assert z.purgar_pendientes() == 0


# --- recuperacion ----------------------------------------------------------


def test_se_pueden_listar_los_pendientes():
    """Si Claude Code reinicia, el id se pierde de la conversacion. Sin forma
    de listarlos, el pendiente queda inalcanzable hasta que lo purgue el tiempo."""
    assert "Sin correos" in z.listar_pendientes_texto(CUENTA)
    z.guardar_pendiente(URL, {"subject": "Cotizacion"}, "para: cliente@x.com | Cotizacion")
    salida = z.listar_pendientes_texto(CUENTA)
    assert "cliente@x.com" in salida
    assert "Cotizacion" in salida


def test_el_listado_ignora_archivos_corruptos(dir_temporal):
    z.guardar_pendiente(URL, {}, "bueno")
    dir_temporal.mkdir(parents=True, exist_ok=True)
    (dir_temporal / "roto.json").write_text("{no es json", encoding="utf-8")
    salida = z.listar_pendientes_texto(CUENTA)
    assert "bueno" in salida


# --- aislamiento entre cuentas -----------------------------------------------
#
# Todas las instancias comparten pendientes/. Antes de este chequeo, la instancia
# de una cuenta listaba los borradores de la otra y podia intentar enviarlos.

OTRA = z.Cuenta(
    nombre="otra",
    client_id="cid2",
    client_secret="cs2",
    refresh_token="rt2",
    account_id="222",
)


def test_el_listado_solo_muestra_los_de_la_cuenta():
    z.guardar_pendiente(URL, {}, "para: mio@x.com | propio")
    z.guardar_pendiente(z.url_enviar(OTRA), {}, "para: ajeno@x.com | ajeno")
    salida = z.listar_pendientes_texto(CUENTA)
    assert "propio" in salida
    assert "ajeno@x.com" not in salida  # ni siquiera el destinatario se filtra
    assert "1 pendiente(s) de otras cuentas" in salida


def test_sin_propios_pero_con_ajenos_lo_dice():
    z.guardar_pendiente(z.url_enviar(OTRA), {}, "ajeno")
    salida = z.listar_pendientes_texto(CUENTA)
    assert "Sin correos pendientes" in salida
    assert "otras cuentas" in salida


def test_leer_un_pendiente_ajeno_falla_claro():
    ident = z.guardar_pendiente(z.url_enviar(OTRA), {}, "ajeno")
    with pytest.raises(z.ZohoError, match="otra cuenta"):
        z.leer_pendiente(ident, CUENTA)
    assert z.leer_pendiente(ident, OTRA)["resumen"] == "ajeno"


def test_mismo_account_id_en_otra_region_es_ajeno():
    """La URL incluye el dominio del centro de datos, no solo el accountId."""
    eu = z.Cuenta(
        nombre="eu",
        client_id="c",
        client_secret="s",
        refresh_token="r",
        account_id="111",
        region="eu",
    )
    ident = z.guardar_pendiente(URL, {}, "de com")
    with pytest.raises(z.ZohoError, match="otra cuenta"):
        z.leer_pendiente(ident, eu)


def test_account_id_que_es_prefijo_de_otro_no_se_confunde():
    """111 no debe reclamar los pendientes de 1112."""
    larga = z.Cuenta(
        nombre="larga",
        client_id="c",
        client_secret="s",
        refresh_token="r",
        account_id="1112",
    )
    ident = z.guardar_pendiente(z.url_enviar(larga), {}, "de 1112")
    with pytest.raises(z.ZohoError, match="otra cuenta"):
        z.leer_pendiente(ident, CUENTA)
