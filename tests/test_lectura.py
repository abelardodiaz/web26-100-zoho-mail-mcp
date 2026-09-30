import pytest

import zoho_mail_mcp as z

# --- referencia carpeta/mensaje -------------------------------------------


def test_referencia_ida_y_vuelta():
    ref = z.ref_mensaje("77", "1234567890")
    assert ref == "77/1234567890"
    assert z.parse_ref(ref) == ("77", "1234567890")


def test_referencia_invalida_falla_claro():
    with pytest.raises(z.ZohoError, match="carpeta/mensaje"):
        z.parse_ref("1234567890")


def test_referencia_con_partes_vacias_falla():
    with pytest.raises(z.ZohoError, match="carpeta/mensaje"):
        z.parse_ref("/1234567890")


# --- formato de fecha ------------------------------------------------------


def test_epoch_ms_se_vuelve_fecha_legible():
    # 1786718302500 ms -> 2026-08-12 en UTC. Se compara el prefijo para no
    # atarse a la zona horaria de la maquina que corre las pruebas.
    salida = z.fecha_legible("1786718302500")
    assert salida.startswith("2026-")
    assert len(salida) == 16  # YYYY-MM-DD HH:MM


def test_fecha_basura_se_devuelve_tal_cual():
    assert z.fecha_legible("no-es-un-numero") == "no-es-un-numero"
    assert z.fecha_legible("") == ""


# --- formateo del listado --------------------------------------------------


MENSAJE = {
    "folderId": "1000000000000000014",
    "messageId": "1700000000000000001",
    "subject": "Re: Cotizacion de servicio",
    "fromAddress": "jose@ejemplo.com",
    "toAddress": "&lt;destino@ejemplo.com&gt;",
    "receivedTime": "1786554422670",
    "hasAttachment": "0",
}


def test_listado_emite_referencia_utilizable():
    salida = z.formatear_lista([MENSAJE])
    assert "[1000000000000000014/1700000000000000001]" in salida
    assert "jose@ejemplo.com" in salida


def test_listado_desescapa_html():
    """La API devuelve los destinatarios con entidades HTML."""
    salida = z.formatear_lista([dict(MENSAJE, fromAddress="&quot;Jose&quot; &lt;j@x.com&gt;")])
    assert "&quot;" not in salida and "&lt;" not in salida
    assert '"Jose" <j@x.com>' in salida


def test_listado_marca_los_que_traen_adjunto():
    assert "[adj]" in z.formatear_lista([dict(MENSAJE, hasAttachment="1")])
    assert "[adj]" not in z.formatear_lista([MENSAJE])


def test_listado_vacio_lo_dice():
    assert z.formatear_lista([]) == "Sin mensajes."


def test_sin_asunto_no_queda_en_blanco():
    assert "(sin asunto)" in z.formatear_lista([dict(MENSAJE, subject="")])


# --- adjuntos --------------------------------------------------------------


def test_adjuntos_usan_attachmentSize_no_size():
    """La API devuelve attachmentSize. Asumir 'size' reportaba 0 KB siempre."""
    datos = {
        "attachments": [
            {"attachmentSize": 147741, "attachmentName": "reporte.csv", "attachmentId": "1400600"}
        ]
    }
    salida = z.formatear_adjuntos(datos)
    assert "reporte.csv" in salida
    assert "1400600" in salida
    assert "144 KB" in salida


def test_los_archivos_chicos_no_se_muestran_como_0_kb():
    """79 bytes mostrado como '0 KB' parece un error aunque no lo sea."""
    assert z.tam_legible(79) == "79 B"
    assert z.tam_legible(0) == "0 B"
    assert z.tam_legible(2048) == "2 KB"
    assert z.tam_legible(3 * 1024 * 1024) == "3.0 MB"


def test_sin_adjuntos_lo_dice():
    assert "no tiene adjuntos" in z.formatear_adjuntos({"attachments": []})
    assert "no tiene adjuntos" in z.formatear_adjuntos({})


# --- resolucion de carpeta -------------------------------------------------


CARPETAS = [
    {"folderId": "1000000000000000014", "folderName": "Inbox"},
    {"folderId": "1000000000000000020", "folderName": "Sent"},
]


def test_carpeta_numerica_se_acepta_tal_cual():
    """Sin el scope de carpetas, pasar el folderId directo sigue funcionando."""
    assert z.carpeta_es_id("1000000000000000014") is True
    assert z.carpeta_es_id("Inbox") is False


def test_nombre_de_carpeta_no_distingue_mayusculas():
    assert z.buscar_carpeta("inbox", CARPETAS) == "1000000000000000014"
    assert z.buscar_carpeta("SENT", CARPETAS) == "1000000000000000020"


def test_carpeta_inexistente_dice_cuales_hay():
    with pytest.raises(z.ZohoError) as e:
        z.buscar_carpeta("Archivo", CARPETAS)
    assert "Inbox" in str(e.value) and "Sent" in str(e.value)


def test_error_de_scope_se_traduce_a_instruccion_accionable():
    """INVALID_OAUTHSCOPE es el error real observado el 2026-08-14."""
    err = z.ZohoError("Zoho respondio 401 en GET .../folders: "
                      '[2, {"errorCode":"INVALID_OAUTHSCOPE","status":"401"}]')
    traducido = z.explicar_scope_carpetas(err, "api-console.zoho.com")
    assert "ZohoMail.folders.READ" in traducido
    assert "folderId" in traducido


def test_otro_error_no_se_disfraza_de_problema_de_scope():
    err = z.ZohoError("Zoho respondio 500 en GET .../folders: boom")
    assert z.explicar_scope_carpetas(err, "api-console.zoho.com") is None


# --- HTML a texto ----------------------------------------------------------


def test_el_css_no_llega_al_texto():
    """Observado el 2026-08-14: un correo de Facebook traia 8 KB de CSS antes
    de la primera palabra util."""
    bruto = "<style>div .x { display: none }</style><p>Hola mundo</p>"
    salida = z.html_a_texto(bruto)
    assert "display" not in salida
    assert salida == "Hola mundo"


def test_los_scripts_y_el_head_tambien_se_van():
    assert "alert" not in z.html_a_texto("<script>alert(1)</script><p>ok</p>")
    assert "titulo" not in z.html_a_texto("<head><title>titulo</title></head><p>ok</p>")


def test_los_saltos_de_bloque_se_conservan():
    assert z.html_a_texto("<p>uno</p><p>dos</p>") == "uno\ndos"
    assert z.html_a_texto("uno<br>dos") == "uno\ndos"


def test_las_entidades_se_desescapan():
    assert z.html_a_texto("<p>caf&eacute; &amp; pan</p>") == "café & pan"


def test_el_espacio_duro_se_vuelve_espacio_normal():
    assert z.html_a_texto("<p>a&nbsp;b</p>") == "a b"


def test_no_deja_bloques_de_lineas_en_blanco():
    assert "\n\n\n" not in z.html_a_texto("<p>a</p><br><br><br><br><p>b</p>")


def test_cuerpo_vacio_no_revienta():
    assert z.html_a_texto("") == ""
    assert z.html_a_texto(None) == ""


# --- registro en el servidor ----------------------------------------------


async def test_las_herramientas_de_lectura_estan_registradas():
    nombres = {t.name for t in await z.SERVIDOR.list_tools()}
    assert {
        "listar_carpetas",
        "listar_correos",
        "buscar_correos",
        "leer_correo",
        "listar_adjuntos",
        "descargar_adjunto",
    } <= nombres


def test_el_limite_se_topa_en_100():
    assert z._tope(500) == 100
    assert z._tope(0) == 1
    assert z._tope(20) == 20
