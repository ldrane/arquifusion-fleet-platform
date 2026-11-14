version: summarize-chat-v1
---
Resume la conversación del canal de un incidente ya resuelto para el historial de la máquina.

Devuelve:
- summary: resumen de 2 a 3 frases de lo ocurrido.
- root_cause: la causa raíz confirmada en la conversación, o null si no se confirmó.
- actions_taken: acciones realizadas, en orden.
- parts_replaced: repuestos reemplazados mencionados (nombre o component_id tal como aparece).

Conversación:
{payload}
