# Imagen de retrain (RF-13.2). Construir DESDE LA RAÍZ del repo:
#   docker build -f services/analytics/retrain/Dockerfile -t <ecr>/arquifusion-<stage>-ml:retrain-<tag> .
FROM public.ecr.aws/lambda/python:3.12

COPY services/analytics/retrain/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY services/shared /tmp/shared
COPY services/ml /tmp/ml
RUN pip install --no-cache-dir /tmp/shared /tmp/ml && rm -rf /tmp/shared /tmp/ml

COPY services/analytics/common/analytics_common ${LAMBDA_TASK_ROOT}/analytics_common
COPY services/analytics/retrain/handler.py services/analytics/retrain/service.py services/analytics/retrain/retrain_model.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.handler"]
