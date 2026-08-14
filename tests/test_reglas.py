from pathlib import Path

import pytest

import zoho_mail_mcp as z


def test_el_modulo_define_sus_constantes():
    assert z.BASE == "https://mail.zoho.com/api"
    assert z.DIAS_PURGA_PENDIENTES == 7


# --- rutas Windows <-> WSL -------------------------------------------------
#
# El cliente (Claude Code) corre en Windows y el servidor en WSL. Toda ruta que
# cruza esa frontera hay que traducirla; es la misma frontera que ya costo un
# refresh token en la Fase 1.


def test_ruta_windows_se_traduce_a_wsl():
    assert z.normalizar_ruta(r"C:\Users\usuario\doc.pdf") == Path("/mnt/c/Users/usuario/doc.pdf")
    assert z.normalizar_ruta("D:/datos/x.png") == Path("/mnt/d/datos/x.png")


def test_la_unidad_se_pasa_a_minuscula():
    assert z.normalizar_ruta(r"C:\x.txt") == Path("/mnt/c/x.txt")
    assert z.normalizar_ruta(r"e:\x.txt") == Path("/mnt/e/x.txt")


def test_ruta_windows_entre_comillas_tambien():
    esperado = Path("/mnt/c/Users/usuario/un doc.pdf")
    assert z.normalizar_ruta('"C:\\Users\\usuario\\un doc.pdf"') == esperado
    assert z.normalizar_ruta("'C:\\Users\\usuario\\un doc.pdf'") == esperado


def test_ruta_posix_se_respeta():
    assert z.normalizar_ruta("/home/usuario/x.txt") == Path("/home/usuario/x.txt")


def test_tilde_se_expande():
    assert z.normalizar_ruta("~/x.txt") == Path.home() / "x.txt"


def test_ruta_vacia_falla_en_vez_de_apuntar_al_cwd():
    with pytest.raises(z.ZohoError, match="vacia"):
        z.normalizar_ruta("   ")


# --- validacion del destino ------------------------------------------------


def test_destino_en_directorio_inexistente_falla_antes_de_la_red(tmp_path):
    with pytest.raises(z.ZohoError, match="no existe"):
        z.validar_destino(str(tmp_path / "no-existe" / "a.pdf"))


def test_destino_que_es_un_directorio_falla(tmp_path):
    with pytest.raises(z.ZohoError, match="directorio"):
        z.validar_destino(str(tmp_path))


def test_destino_valido_devuelve_path(tmp_path):
    assert z.validar_destino(str(tmp_path / "a.pdf")) == tmp_path / "a.pdf"


def test_destino_existente_no_se_pisa_en_silencio(tmp_path):
    """Sobrescribir la descarga previa sin avisar es perdida de datos."""
    p = tmp_path / "ya-esta.pdf"
    p.write_bytes(b"contenido viejo")
    with pytest.raises(z.ZohoError, match="[Yy]a existe"):
        z.validar_destino(str(p))
    assert p.read_bytes() == b"contenido viejo"


def test_destino_existente_se_pisa_si_se_pide_explicito(tmp_path):
    p = tmp_path / "ya-esta.pdf"
    p.write_bytes(b"viejo")
    assert z.validar_destino(str(p), sobrescribir=True) == p


# --- nombre de archivo sugerido -------------------------------------------


def test_nombre_seguro_quita_separadores():
    """El attachmentName viene del remitente: es entrada no confiable."""
    assert z.nombre_seguro("../../etc/passwd") == "passwd"
    assert z.nombre_seguro(r"..\..\windows\system32\x.dll") == "x.dll"


def test_nombre_seguro_conserva_lo_normal():
    assert z.nombre_seguro("reporte.csv") == "reporte.csv"
    assert z.nombre_seguro("Cotizacion 2026 (final).pdf") == "Cotizacion 2026 (final).pdf"


def test_nombre_seguro_tiene_respaldo_si_queda_vacio():
    assert z.nombre_seguro("") == "adjunto"
    assert z.nombre_seguro("///") == "adjunto"


# --- Regla 1: el remitente se valida contra los alias confirmados ----------
#
# Las tres reglas de esta seccion salen de errores reales observados el
# 2026-08-05 mandando por el MCP remoto. Ver el spec.

REMS = [
    z.Remitente("remitente@ejemplo.com", "Remitente Ejemplo"),
    z.Remitente("sinnombre@ejemplo.com", ""),
]


def test_alias_valido_se_resuelve_sin_importar_mayusculas():
    assert z.resolver_remitente("Remitente@Ejemplo.com", REMS) == REMS[0]


def test_alias_con_espacios_alrededor_se_resuelve():
    assert z.resolver_remitente("  remitente@ejemplo.com  ", REMS) == REMS[0]


def test_alias_inexistente_falla_y_dice_cuales_hay():
    """Sin esto, Zoho manda desde el remitente predeterminado de la cuenta."""
    with pytest.raises(z.ZohoError) as e:
        z.resolver_remitente("noexiste@ejemplo.com", REMS)
    assert "remitente@ejemplo.com" in str(e.value)


def test_remitente_vacio_falla():
    with pytest.raises(z.ZohoError):
        z.resolver_remitente("", REMS)


def test_alias_dentro_de_un_from_compuesto_tambien_se_resuelve():
    """Si el que llama repite el formato 'Nombre <correo>', no debe romperse."""
    assert z.resolver_remitente('"Remitente" <remitente@ejemplo.com>', REMS) == REMS[0]


# --- Regla 2: el nombre para mostrar se compone solo ----------------------


def test_nombre_para_mostrar_se_compone():
    assert z.componer_from(REMS[0]) == '"Remitente Ejemplo" <remitente@ejemplo.com>'


def test_sin_nombre_para_mostrar_va_el_correo_pelon():
    assert z.componer_from(REMS[1]) == "sinnombre@ejemplo.com"


def test_las_comillas_del_nombre_no_rompen_la_cabecera():
    r = z.Remitente("x@y.com", 'Ana "La Jefa" Ruiz')
    assert z.componer_from(r) == '"Ana La Jefa Ruiz" <x@y.com>'


# --- destinatarios ---------------------------------------------------------


def test_destinatarios_aceptan_lista_o_cadena():
    assert z.normalizar_destinatarios(["a@x.com", "b@x.com"]) == ["a@x.com", "b@x.com"]
    assert z.normalizar_destinatarios("a@x.com, b@x.com") == ["a@x.com", "b@x.com"]
    assert z.normalizar_destinatarios("a@x.com; b@x.com") == ["a@x.com", "b@x.com"]


def test_destinatarios_se_limpian_y_no_se_repiten():
    assert z.normalizar_destinatarios([" a@x.com ", "", "a@x.com"]) == ["a@x.com"]


def test_destinatario_sin_arroba_falla():
    with pytest.raises(z.ZohoError, match="no parece un correo"):
        z.normalizar_destinatarios(["esto no es un correo"])


def test_destinatarios_vacios_dan_lista_vacia():
    assert z.normalizar_destinatarios(None) == []
    assert z.normalizar_destinatarios("") == []


# --- Regla 3 y armado del payload -----------------------------------------


def test_payload_fija_reply_to_al_remitente():
    """La interfaz web de Zoho arrastra un Reply-To propio; se pisa a proposito."""
    p = z.construir_payload(
        remitente=REMS[0],
        para=["cliente@ejemplo.com"],
        cc=[],
        cco=[],
        asunto="Hola",
        cuerpo="<p>Hola</p>",
        formato="html",
        adjuntos=[],
    )
    assert p["replyTo"] == "remitente@ejemplo.com"
    assert p["fromAddress"] == '"Remitente Ejemplo" <remitente@ejemplo.com>'
    assert p["toAddress"] == "cliente@ejemplo.com"
    assert p["mailFormat"] == "html"
    assert p["subject"] == "Hola"
    assert p["content"] == "<p>Hola</p>"
    assert "ccAddress" not in p
    assert "bccAddress" not in p
    assert "attachments" not in p


def test_payload_junta_destinatarios_con_coma():
    p = z.construir_payload(
        remitente=REMS[0],
        para=["a@x.com", "b@x.com"],
        cc=["c@x.com"],
        cco=["d@x.com"],
        asunto="s",
        cuerpo="c",
        formato="plaintext",
        adjuntos=[],
    )
    assert p["toAddress"] == "a@x.com,b@x.com"
    assert p["ccAddress"] == "c@x.com"
    assert p["bccAddress"] == "d@x.com"
    assert p["mailFormat"] == "plaintext"


def test_payload_sin_destinatarios_falla():
    with pytest.raises(z.ZohoError, match="destinatario"):
        z.construir_payload(
            remitente=REMS[0], para=[], cc=[], cco=[], asunto="s",
            cuerpo="c", formato="html", adjuntos=[],
        )


def test_solo_cco_ya_cuenta_como_destinatario():
    p = z.construir_payload(
        remitente=REMS[0], para=[], cc=[], cco=["d@x.com"], asunto="s",
        cuerpo="c", formato="html", adjuntos=[],
    )
    assert p["bccAddress"] == "d@x.com"
    assert "toAddress" not in p


def test_formato_invalido_falla():
    with pytest.raises(z.ZohoError, match="html"):
        z.construir_payload(
            remitente=REMS[0], para=["a@x.com"], cc=[], cco=[], asunto="s",
            cuerpo="c", formato="markdown", adjuntos=[],
        )


def test_asunto_vacio_falla():
    """Un correo sin asunto desde una cuenta de negocio se lee como spam."""
    with pytest.raises(z.ZohoError, match="asunto"):
        z.construir_payload(
            remitente=REMS[0], para=["a@x.com"], cc=[], cco=[], asunto="   ",
            cuerpo="c", formato="html", adjuntos=[],
        )


def test_payload_incluye_los_tres_campos_de_cada_adjunto():
    a = z.AdjuntoSubido(nombre="doc.pdf", ruta="/api/att/1", store="store-1", bytes_=1234)
    p = z.construir_payload(
        remitente=REMS[0], para=["a@x.com"], cc=[], cco=[], asunto="s",
        cuerpo="c", formato="html", adjuntos=[a],
    )
    assert p["attachments"] == [
        {"attachmentName": "doc.pdf", "attachmentPath": "/api/att/1", "storeName": "store-1"}
    ]


def test_el_payload_no_lleva_mode():
    """El 'mode' distingue borrador de envio y se pone al llamar, no aqui.
    Guardarlo en el pendiente haria que confirmar creara otro borrador."""
    p = z.construir_payload(
        remitente=REMS[0], para=["a@x.com"], cc=[], cco=[], asunto="s",
        cuerpo="c", formato="html", adjuntos=[],
    )
    assert "mode" not in p


# --- validacion de adjuntos ------------------------------------------------


def test_archivo_inexistente_falla(tmp_path):
    with pytest.raises(z.ZohoError, match="No existe"):
        z.validar_adjuntos([str(tmp_path / "fantasma.pdf")], 20)


def test_archivo_vacio_falla(tmp_path):
    p = tmp_path / "vacio.pdf"
    p.write_bytes(b"")
    with pytest.raises(z.ZohoError, match="vacio"):
        z.validar_adjuntos([str(p)], 20)


def test_archivo_que_excede_el_limite_dice_su_tamano_real(tmp_path):
    p = tmp_path / "grande.bin"
    p.write_bytes(b"x" * (2 * 1024 * 1024))
    with pytest.raises(z.ZohoError) as e:
        z.validar_adjuntos([str(p)], 1)
    assert "2.0 MB" in str(e.value) and "1 MB" in str(e.value)


def test_la_suma_de_varios_tambien_se_valida(tmp_path):
    for n in ("a.bin", "b.bin"):
        (tmp_path / n).write_bytes(b"x" * (700 * 1024))
    with pytest.raises(z.ZohoError, match="suman"):
        z.validar_adjuntos([str(tmp_path / "a.bin"), str(tmp_path / "b.bin")], 1)


def test_adjuntos_validos_devuelven_ruta_y_tamano(tmp_path):
    p = tmp_path / "ok.pdf"
    p.write_bytes(b"x" * 100)
    assert z.validar_adjuntos([str(p)], 20) == [(p, 100)]


def test_sin_adjuntos_no_falla():
    assert z.validar_adjuntos([], 20) == []
    assert z.validar_adjuntos(None, 20) == []


def test_un_directorio_no_pasa_por_adjunto(tmp_path):
    with pytest.raises(z.ZohoError, match="No existe o no es un archivo"):
        z.validar_adjuntos([str(tmp_path)], 20)
