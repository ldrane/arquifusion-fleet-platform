version: diagnose-v1
---
Diagnostica la anomalía de una máquina a partir de sus variables más desviadas (top_factors, con z-score frente a su propio historial), su última lectura y sus incidentes recientes.

Devuelve:
- probable_cause: la causa técnica más probable, en una frase.
- suggested_action: la acción concreta que debe hacer el técnico, en una frase.
- confidence: entre 0 y 1. Usa valores bajos si la evidencia es débil o contradictoria.
- parts_suggested: component_id de repuestos probables, elegidos SOLO de candidate_parts. Si no hay candidatos, devuelve una lista vacía.

Considera el comportamiento conjunto de las variables: por ejemplo, temperatura + vibración altas suelen indicar fricción o falla de rodamientos; consumo alto con carga normal sugiere inyectores o filtros.

Datos:
{payload}
