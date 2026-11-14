version: summarize-by-role-v1
---
Redacta la notificación de un incidente para cada rol indicado en roles. Cada rol recibe información distinta:
- operador: qué hacer con la máquina ahora (detenerla, reducir carga, esperar al técnico).
- tecnico: detalle técnico (variables, valores, diagnóstico, acción sugerida).
- mantenimiento: técnico asignado, repuestos y prioridad.
- supervisor: impacto en la zona y estado de la atención.
- admin y gerencia: impacto en la operación (máquina detenida, tiempo estimado), sin detalle técnico.

Para cada rol devuelve title (máximo 60 caracteres) y body (máximo 280 caracteres).

Incidente:
{payload}
