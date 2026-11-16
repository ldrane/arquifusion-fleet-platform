# Imagen de la Lambda sim-driver (TAREA-07). Construir DESDE LA RAÍZ del repo:
#   docker build -f services/ingest/sim_driver/Dockerfile -t <ecr>/arquifusion-<stage>-ml:sim-driver-<tag> .
FROM public.ecr.aws/lambda/python:3.12

COPY services/ingest/sim_driver/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Librerías comunes (Persona B): handler.py importa arquifusion_shared.
COPY services/shared /tmp/shared
RUN pip install --no-cache-dir /tmp/shared && rm -rf /tmp/shared

# Generador de telemetría compartido con el simulador local y seeds del contrato.
COPY simulator ${LAMBDA_TASK_ROOT}/simulator
COPY contracts/fixtures/seed ${LAMBDA_TASK_ROOT}/seed
COPY services/ingest/sim_driver/handler.py services/ingest/sim_driver/service.py ${LAMBDA_TASK_ROOT}/

ENV SIMULATOR_SEED_DIR=/var/task/seed

CMD ["handler.handler"]
