"""Módulos internos de la Lambda `procesar` (RF-02, RF-09, RNF-07).

- `config`: configuración desde variables de entorno.
- `message`: parseo del mensaje SQS que deja API Gateway.
- `rules`: capa 1, umbrales por tipo de máquina.
- `baseline`: capa 2, baseline EWMA y z-score (propio y de cohorte).
- `model`: capa 3, IsolationForest cargado desde S3.
- `scoring`: combinación de capas en health score, severidad y top-3 factores.
- `repository`: acceso a DynamoDB, Firehose y EventBridge.
"""
