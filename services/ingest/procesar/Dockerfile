# Imagen de la Lambda procesar (RF-02, MH-AI-01). Construir DESDE LA RAÍZ del repo:
#   docker build -f services/ingest/procesar/Dockerfile -t <ecr>/arquifusion-<stage>-ml:procesar-<tag> .
FROM public.ecr.aws/lambda/python:3.12

COPY services/ingest/procesar/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Librerías comunes: arquifusion_shared (Persona B) y arquifusion_ml (Persona A).
COPY services/shared /tmp/shared
COPY services/ml /tmp/ml
RUN pip install --no-cache-dir /tmp/shared /tmp/ml && rm -rf /tmp/shared /tmp/ml

COPY services/ingest/procesar/handler.py services/ingest/procesar/service.py \
     services/ingest/procesar/thresholds_default.json ${LAMBDA_TASK_ROOT}/
COPY services/ingest/procesar/ingest_procesar ${LAMBDA_TASK_ROOT}/ingest_procesar

CMD ["handler.handler"]
