version: summarize-chat-v2
---
Resume la conversación del chat de un incidente ya resuelto para el historial de la máquina.

Regla estricta: usa ÚNICAMENTE lo que se dijo en los mensajes de la conversación de abajo. No agregues notas de resolución, diagnósticos, datos de telemetría ni información que no aparezca escrita en el chat. Si algo no se mencionó en la conversación, no lo incluyas.

Devuelve:
- summary: resumen de 2 a 3 frases de lo que se conversó en el chat (quién reportó qué, qué se acordó, cómo terminó la conversación).
- root_cause: la causa raíz si se confirmó explícitamente en la conversación; null si no se confirmó en el chat.
- actions_taken: acciones realizadas que se mencionan en la conversación (incluye las acciones rápidas `quick_action`), en orden. Lista vacía si no hay.
- parts_replaced: repuestos que en la conversación se dice que fueron reemplazados (nombre o component_id tal como aparece en el chat). Lista vacía si no hay.

Conversación (mensajes del chat en orden; `role` es el rol de quien escribe):
{payload}
