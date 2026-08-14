# docs/incoming/ - bandeja de memos de la flota

Los proyectos de la flota no comparten memoria entre sesiones. El canal para pasarse
informacion es un memo markdown dejado en el `docs/incoming/` del proyecto **destino**.

Aqui llegan los memos dirigidos a **web26-100**: bugs, correcciones de supuestos, handoffs,
peticiones, entregas y avisos.

## Convencion de nombre

    NNN-YYYYMMDDHHMMSS-from-claude-X-to-claude-Y-tema.md

## Regla de salida - importante

Cuando un memo queda incorporado, **muevelo a `docs/procesados/`**. No lo borres: sirve de
auditoria. Sin eso el hook de arranque lo sigue anunciando para siempre y el aviso se vuelve
ruido que nadie lee.

## Para escribir a otro proyecto

Usa la skill `reportar-a-proyecto`. **Nunca edites el codigo ni los docs del otro proyecto**:
esa sesion tiene contexto que la tuya no ve.
