
- Problemas
1. 🔴 El simulador de A no usa tus seeds. Genera su propia flota y no coincide con la tuya en nada importante:
   - Son 84 máquinas contra tus 100.
   - Los modelos no coinciden en ninguna máquina (por ejemplo AF-EX350 contra CAT-336).
   - La zona es distinta en 67 de las 84 máquinas que comparten ID. Por ejemplo, EX-023 está en este para el simulador y en norte en tus seeds.
   - Las coordenadas están a unos 500 km entre sí (−14.4 contra −11.95).

   Consecuencias: en el mapa las máquinas saltarían de lugar, la búsqueda de stock no encontraría MODEL#AF-EX350 en el catálogo, y las reglas de zona darían resultados incoherentes. Tu runbook dice que A debe usar machines.json.

# TO DO 
- Quiero que hagas un escaneo completo y revises que las 3 partes se interconecten con datos para evitar problemas como el que se detecto arriba
- Anota todos esos puntos en un markdown 
- Actua siempre como manager, activa workers paara que revisen por sus lados las 3 partes y te ayuden con el reporte.
