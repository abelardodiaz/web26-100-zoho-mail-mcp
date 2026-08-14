"""Pendientes en disco.

Van a disco y no a memoria a proposito: si Claude Code reinicia entre preparar
y confirmar, el correo (y los adjuntos ya subidos a Zoho) no se pierden.
"""

import os
import time

import pytest

import zoho_mail_mcp as z


@pytest.fixture(autouse=True)
def dir_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(z, "DIR_PENDIENTES", tmp_path / "pendientes")
    return tmp_path / "pendientes"


def test_guardar_y_leer_ida_y_vuelta():
    ident = z.guardar_pendiente("https://mail.zoho.com/x", {"subject": "hola"}, "resumen")
    p = z.leer_pendiente(ident)
    assert p["payload"] == {"subject": "hola"}
    assert p["url"] == "https://mail.zoho.com/x"
    assert p["resumen"] == "resumen"


def test_el_archivo_queda_con_permisos_600(dir_temporal):
    ident = z.guardar_pendiente("u", {}, "r")
    modo = (dir_temporal / f"{ident}.json").stat().st_mode & 0o777
    assert modo == 0o600


def test_no_quedan_archivos_temporales(dir_temporal):
    z.guardar_pendiente("u", {}, "r")
    assert list(dir_temporal.glob("*.tmp")) == []


def test_dos_pendientes_seguidos_no_colisionan():
    a = z.guardar_pendiente("u", {"n": 1}, "a")
    b = z.guardar_pendiente("u", {"n": 2}, "b")
    assert a != b
    assert z.leer_pendiente(a)["payload"] == {"n": 1}
    assert z.leer_pendiente(b)["payload"] == {"n": 2}


def test_el_contenido_sobrevive_acentos(dir_temporal):
    ident = z.guardar_pendiente("u", {"subject": "Cotización año 2026"}, "r")
    crudo = (dir_temporal / f"{ident}.json").read_text(encoding="utf-8")
    assert "Cotización año 2026" in crudo
    assert z.leer_pendiente(ident)["payload"]["subject"] == "Cotización año 2026"


def test_pendiente_inexistente_falla_claro():
    with pytest.raises(z.ZohoError, match="No hay un pendiente"):
        z.leer_pendiente("20260805120000-abcdef")


def test_pendiente_corrupto_falla_claro(dir_temporal):
    dir_temporal.mkdir(parents=True, exist_ok=True)
    (dir_temporal / "roto.json").write_text("{no es json", encoding="utf-8")
    with pytest.raises(z.ZohoError, match="ilegible"):
        z.leer_pendiente("roto")


def test_pendiente_sin_los_campos_esperados_falla(dir_temporal):
    dir_temporal.mkdir(parents=True, exist_ok=True)
    (dir_temporal / "incompleto.json").write_text('{"resumen": "x"}', encoding="utf-8")
    with pytest.raises(z.ZohoError, match="ilegible"):
        z.leer_pendiente("incompleto")


def test_id_con_separadores_de_ruta_se_rechaza():
    """El id llega desde afuera: no debe poder apuntar fuera del directorio."""
    for malo in ("../../etc/passwd", "a/b", r"a\b", "/etc/passwd"):
        with pytest.raises(z.ZohoError, match="identificador"):
            z.leer_pendiente(malo)


def test_borrar_quita_el_archivo(dir_temporal):
    ident = z.guardar_pendiente("u", {}, "r")
    z.borrar_pendiente(ident)
    assert not (dir_temporal / f"{ident}.json").exists()


def test_borrar_dos_veces_no_truena():
    ident = z.guardar_pendiente("u", {}, "r")
    z.borrar_pendiente(ident)
    z.borrar_pendiente(ident)


def test_purga_borra_viejos_y_respeta_recientes(dir_temporal):
    viejo = z.guardar_pendiente("u", {}, "viejo")
    nuevo = z.guardar_pendiente("u", {}, "nuevo")
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
    assert "Sin correos" in z.listar_pendientes_texto()
    z.guardar_pendiente("u", {"subject": "Cotizacion"}, "para: cliente@x.com | Cotizacion")
    salida = z.listar_pendientes_texto()
    assert "cliente@x.com" in salida
    assert "Cotizacion" in salida


def test_el_listado_ignora_archivos_corruptos(dir_temporal):
    z.guardar_pendiente("u", {}, "bueno")
    dir_temporal.mkdir(parents=True, exist_ok=True)
    (dir_temporal / "roto.json").write_text("{no es json", encoding="utf-8")
    salida = z.listar_pendientes_texto()
    assert "bueno" in salida
