"""Datos maestros de ArquiFusion (C1). Generación 100% determinista.

Funciones puras, sin AWS: el mismo código produce siempre los mismos datos.
Los consume:
  - scripts/seed.py            -> carga en DynamoDB
  - contracts/fixtures/seed/   -> JSON para el simulador (A) y la SFN (B)

IDs según contratos.md §1: EX-023, TEC-07, WH-01, CMP-014.
Si cambias algo aquí, sube SEED_VERSION y vuelve a exportar los fixtures.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

SEED_VERSION = 4  # v2: WH-04 oeste, expected_interval_s=60, reglas §10. v3: ~8 % de mantenimientos vencidos (no 53 %)
# v4: flota más variada (19 modelos / 8 marcas, distribución por zona según el tipo de trabajo, horómetro según la
#     antigüedad del modelo, estados iniciales maintenance/stopped), 16 técnicos con cargas y disponibilidad distintas,
#     5 repuestos nuevos y más quiebres/sobrestock. Los IDs (100 máquinas) y los datos del golden path no cambian.
RANDOM_SEED = 27  # Grupo 27
REFERENCE_DATE = date(2026, 11, 14)  # fechas relativas a este día (no a "hoy") para que sea determinista
OVERDUE_RAW_MIN = 38  # sorteo 3..40: 38-40 => mantenimiento vencido (~8 % de la flota)
OPERATION_ID = "OP-01"
# El simulador envía cada 60 s (simulator/cli.py); heartbeat declara silencio a 3x = 180 s (contratos.md §3).
EXPECTED_INTERVAL_S = 60

# --------------------------------------------------------------------------- zonas
# Operación minera ficticia en la sierra central. Cada zona es un círculo de ~1.5 km.
OPERATION_CENTER = (-11.9500, -76.4000)
ZONES = {
    "norte": {"center": (-11.9200, -76.4000), "radius_deg": 0.012},
    "sur": {"center": (-11.9800, -76.4000), "radius_deg": 0.012},
    "este": {"center": (-11.9500, -76.3650), "radius_deg": 0.012},
    "oeste": {"center": (-11.9500, -76.4350), "radius_deg": 0.012},
}

WAREHOUSES = [
    {
        "warehouse_id": "WH-01",
        "name": "Almacén Norte",
        "zone": "norte",
        "location": {"lat": -11.9150, "lon": -76.3950, "zone": "norte"},
    },
    {
        "warehouse_id": "WH-02",
        "name": "Almacén Sur",
        "zone": "sur",
        "location": {"lat": -11.9850, "lon": -76.4050, "zone": "sur"},
    },
    {
        "warehouse_id": "WH-03",
        "name": "Almacén Este",
        "zone": "este",
        "location": {"lat": -11.9480, "lon": -76.3600, "zone": "este"},
    },
    {
        "warehouse_id": "WH-04",
        "name": "Almacén Oeste",
        "zone": "oeste",
        "location": {"lat": -11.9480, "lon": -76.4400, "zone": "oeste"},
    },
]

# --------------------------------------------------------------------------- modelos
# nominal = [media, desviación] de operación normal. Lo usa el simulador (A) como baseline.
MACHINE_MODELS = [
    {
        "model_id": "CAT-336",
        "brand": "Caterpillar",
        "type": "excavator",
        "payload_t": 2.5,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [88, 3],
            "vibration_mm_s": [4.0, 0.6],
            "pressure_bar": [300, 15],
            "fuel_rate_lph": [38, 4],
            "load_pct": [70, 10],
            "speed_kmh": [3, 1.5],
            "rpm": [1800, 80],
        },
    },
    {
        "model_id": "KOM-PC2000",
        "brand": "Komatsu",
        "type": "excavator",
        "payload_t": 12.0,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [90, 3],
            "vibration_mm_s": [4.5, 0.6],
            "pressure_bar": [320, 15],
            "fuel_rate_lph": [110, 8],
            "load_pct": [72, 10],
            "speed_kmh": [2.5, 1.2],
            "rpm": [1800, 80],
        },
    },
    {
        "model_id": "CAT-793F",
        "brand": "Caterpillar",
        "type": "mining_truck",
        "payload_t": 227.0,
        "maintenance_interval_h": 500,
        "nominal": {
            "temperature_c": [92, 3],
            "vibration_mm_s": [3.5, 0.5],
            "pressure_bar": [180, 10],
            "fuel_rate_lph": [170, 12],
            "load_pct": [75, 15],
            "speed_kmh": [30, 8],
            "rpm": [1700, 90],
        },
    },
    {
        "model_id": "KOM-930E",
        "brand": "Komatsu",
        "type": "mining_truck",
        "payload_t": 290.0,
        "maintenance_interval_h": 500,
        "nominal": {
            "temperature_c": [93, 3],
            "vibration_mm_s": [3.6, 0.5],
            "pressure_bar": [185, 10],
            "fuel_rate_lph": [190, 14],
            "load_pct": [75, 15],
            "speed_kmh": [28, 8],
            "rpm": [1750, 90],
        },
    },
    {
        "model_id": "CAT-994K",
        "brand": "Caterpillar",
        "type": "loader",
        "payload_t": 40.0,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [90, 3],
            "vibration_mm_s": [4.2, 0.6],
            "pressure_bar": [280, 15],
            "fuel_rate_lph": [160, 10],
            "load_pct": [70, 12],
            "speed_kmh": [10, 4],
            "rpm": [1850, 80],
        },
    },
    {
        "model_id": "KOM-WA900",
        "brand": "Komatsu",
        "type": "loader",
        "payload_t": 23.0,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [89, 3],
            "vibration_mm_s": [4.1, 0.6],
            "pressure_bar": [270, 15],
            "fuel_rate_lph": [120, 9],
            "load_pct": [70, 12],
            "speed_kmh": [10, 4],
            "rpm": [1800, 80],
        },
    },
    {
        "model_id": "CAT-D10T",
        "brand": "Caterpillar",
        "type": "bulldozer",
        "payload_t": 0.0,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [91, 3],
            "vibration_mm_s": [5.0, 0.7],
            "pressure_bar": [250, 12],
            "fuel_rate_lph": [70, 6],
            "load_pct": [68, 12],
            "speed_kmh": [6, 2],
            "rpm": [1900, 80],
        },
    },
    {
        "model_id": "KOM-D375A",
        "brand": "Komatsu",
        "type": "bulldozer",
        "payload_t": 0.0,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [91, 3],
            "vibration_mm_s": [5.2, 0.7],
            "pressure_bar": [255, 12],
            "fuel_rate_lph": [75, 6],
            "load_pct": [68, 12],
            "speed_kmh": [6, 2],
            "rpm": [1900, 80],
        },
    },
    {
        "model_id": "EPI-PV271",
        "brand": "Epiroc",
        "type": "drill",
        "payload_t": 0.0,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [87, 3],
            "vibration_mm_s": [6.0, 0.8],
            "pressure_bar": [350, 20],
            "fuel_rate_lph": [90, 7],
            "load_pct": [65, 12],
            "speed_kmh": [1.5, 0.8],
            "rpm": [1800, 70],
        },
    },
    {
        "model_id": "SAN-DR412i",
        "brand": "Sandvik",
        "type": "drill",
        "payload_t": 0.0,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [86, 3],
            "vibration_mm_s": [5.8, 0.8],
            "pressure_bar": [340, 20],
            "fuel_rate_lph": [85, 7],
            "load_pct": [65, 12],
            "speed_kmh": [1.5, 0.8],
            "rpm": [1800, 70],
        },
    },
    # ---- v4: más marcas y modelos (mismos 5 tipos del enum MachineType del OpenAPI)
    {
        "model_id": "HIT-EX1200",
        "brand": "Hitachi",
        "type": "excavator",
        "payload_t": 6.7,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [89, 3],
            "vibration_mm_s": [4.3, 0.6],
            "pressure_bar": [310, 15],
            "fuel_rate_lph": [80, 7],
            "load_pct": [71, 10],
            "speed_kmh": [2.8, 1.3],
            "rpm": [1800, 80],
        },
    },
    {
        "model_id": "LIE-R9400",
        "brand": "Liebherr",
        "type": "excavator",
        "payload_t": 22.0,
        "maintenance_interval_h": 500,
        "nominal": {
            "temperature_c": [91, 3],
            "vibration_mm_s": [4.7, 0.6],
            "pressure_bar": [330, 15],
            "fuel_rate_lph": [150, 11],
            "load_pct": [73, 10],
            "speed_kmh": [2.2, 1.1],
            "rpm": [1800, 80],
        },
    },
    {
        "model_id": "LIE-T284",
        "brand": "Liebherr",
        "type": "mining_truck",
        "payload_t": 363.0,
        "maintenance_interval_h": 500,
        "nominal": {
            "temperature_c": [94, 3],
            "vibration_mm_s": [3.7, 0.5],
            "pressure_bar": [190, 10],
            "fuel_rate_lph": [215, 15],
            "load_pct": [76, 15],
            "speed_kmh": [27, 8],
            "rpm": [1750, 90],
        },
    },
    {
        "model_id": "BEL-75131",
        "brand": "BelAZ",
        "type": "mining_truck",
        "payload_t": 130.0,
        "maintenance_interval_h": 400,
        "nominal": {
            "temperature_c": [90, 3],
            "vibration_mm_s": [3.9, 0.5],
            "pressure_bar": [170, 10],
            "fuel_rate_lph": [120, 10],
            "load_pct": [74, 15],
            "speed_kmh": [32, 8],
            "rpm": [1800, 90],
        },
    },
    {
        "model_id": "VOL-L350H",
        "brand": "Volvo",
        "type": "loader",
        "payload_t": 11.0,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [88, 3],
            "vibration_mm_s": [3.9, 0.6],
            "pressure_bar": [260, 15],
            "fuel_rate_lph": [45, 5],
            "load_pct": [68, 12],
            "speed_kmh": [12, 4],
            "rpm": [1750, 80],
        },
    },
    {
        "model_id": "LIE-L586",
        "brand": "Liebherr",
        "type": "loader",
        "payload_t": 6.0,
        "maintenance_interval_h": 400,
        "nominal": {
            "temperature_c": [87, 3],
            "vibration_mm_s": [3.8, 0.6],
            "pressure_bar": [250, 15],
            "fuel_rate_lph": [32, 4],
            "load_pct": [66, 12],
            "speed_kmh": [13, 4],
            "rpm": [1700, 80],
        },
    },
    {
        "model_id": "LIE-PR776",
        "brand": "Liebherr",
        "type": "bulldozer",
        "payload_t": 0.0,
        "maintenance_interval_h": 400,
        "nominal": {
            "temperature_c": [90, 3],
            "vibration_mm_s": [5.1, 0.7],
            "pressure_bar": [260, 12],
            "fuel_rate_lph": [80, 6],
            "load_pct": [69, 12],
            "speed_kmh": [6, 2],
            "rpm": [1850, 80],
        },
    },
    {
        "model_id": "CAT-MD6250",
        "brand": "Caterpillar",
        "type": "drill",
        "payload_t": 0.0,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [88, 3],
            "vibration_mm_s": [6.2, 0.8],
            "pressure_bar": [345, 20],
            "fuel_rate_lph": [95, 7],
            "load_pct": [66, 12],
            "speed_kmh": [1.5, 0.8],
            "rpm": [1800, 70],
        },
    },
    {
        "model_id": "EPI-D65",
        "brand": "Epiroc",
        "type": "drill",
        "payload_t": 0.0,
        "maintenance_interval_h": 400,
        "nominal": {
            "temperature_c": [85, 3],
            "vibration_mm_s": [5.5, 0.8],
            "pressure_bar": [250, 15],
            "fuel_rate_lph": [45, 5],
            "load_pct": [63, 12],
            "speed_kmh": [2.5, 1.0],
            "rpm": [2000, 80],
        },
    },
]

# Antigüedad de cada modelo en la flota -> rango de horómetro [mín, máx] (h). v4: los modelos recién
# incorporados tienen pocas horas y los veteranos superan las 20 000 h (más contraste en analítica y salud).
MODEL_HOURS = {
    "CAT-336": (2500, 14000),
    "KOM-PC2000": (8000, 26000),
    "HIT-EX1200": (300, 4500),
    "LIE-R9400": (1200, 9000),
    "CAT-793F": (9000, 32000),
    "KOM-930E": (6000, 24000),
    "LIE-T284": (400, 5000),
    "BEL-75131": (12000, 30000),
    "CAT-994K": (5000, 20000),
    "KOM-WA900": (9000, 25000),
    "VOL-L350H": (500, 6000),
    "LIE-L586": (1500, 8000),
    "CAT-D10T": (7000, 22000),
    "KOM-D375A": (10000, 28000),
    "LIE-PR776": (600, 5500),
    "EPI-PV271": (4000, 16000),
    "SAN-DR412i": (2000, 12000),
    "CAT-MD6250": (300, 3500),
    "EPI-D65": (1000, 7000),
}

# prefijo de ID (patrón ^[A-Z]{2}-[0-9]{3,4}$ del OpenAPI), cantidad y modelos por tipo
FLEET_PLAN = [
    # models = [(modelo, peso)]; zones = peso de cada zona (distribución según el tipo de trabajo, v4):
    # el pit norte concentra excavación y carguío, el este es zona de perforación y voladura, el oeste de
    # botaderos (tractores) y los camiones circulan por todas las rutas de acarreo.
    {
        "type": "excavator",
        "prefix": "EX",
        "count": 25,
        "models": [("CAT-336", 4), ("KOM-PC2000", 3), ("HIT-EX1200", 2), ("LIE-R9400", 1)],
        "zones": {"norte": 4, "sur": 3, "este": 2, "oeste": 1},
    },
    {
        "type": "mining_truck",
        "prefix": "CM",
        "count": 35,
        "models": [("CAT-793F", 4), ("KOM-930E", 3), ("LIE-T284", 2), ("BEL-75131", 2)],
        "zones": {"norte": 3, "sur": 3, "este": 2, "oeste": 2},
    },
    {
        "type": "loader",
        "prefix": "CF",
        "count": 15,
        "models": [("CAT-994K", 3), ("KOM-WA900", 2), ("VOL-L350H", 2), ("LIE-L586", 1)],
        "zones": {"norte": 3, "sur": 2, "este": 2, "oeste": 2},
    },
    {
        "type": "bulldozer",
        "prefix": "BD",
        "count": 12,
        "models": [("CAT-D10T", 3), ("KOM-D375A", 2), ("LIE-PR776", 1)],
        "zones": {"norte": 1, "sur": 2, "este": 2, "oeste": 4},
    },
    {
        "type": "drill",
        "prefix": "PF",
        "count": 13,
        "models": [("EPI-PV271", 3), ("SAN-DR412i", 2), ("CAT-MD6250", 2), ("EPI-D65", 1)],
        "zones": {"norte": 1, "sur": 2, "este": 5, "oeste": 1},
    },
]
ZONE_ORDER = ["norte", "sur", "este", "oeste"]

# Máquinas fijadas porque aparecen en contratos.md / openapi.yaml / fixtures del golden path (contracts/fixtures:
# telemetry_batch, scoring_*, anomaly_detected, incident_state_changed usan EX-023; machine_silent usa CM-004/sur).
# EX-023 conserva ubicación y horómetro de v3 para que el ETA del scoring (TEC-07 0.98, TEC-01 2.º) no cambie.
PINNED_MACHINES = {
    "EX-023": {
        "model": "CAT-336",
        "zone": "norte",
        "location": {"lat": -11.913239, "lon": -76.39975, "zone": "norte"},
        "operating_hours": 3582.1,
        "health_score": 85,
        "status": "operational",
    },
    "CM-004": {"zone": "sur", "status": "operational"},
}
# Estado inicial (MachineStatus): las máquinas con mantenimiento vencido entran al taller con esta probabilidad
# y algunas quedan detenidas en reserva. El simulador respeta este estado (envía state=maintenance/stopped).
OVERDUE_IN_SHOP_P = 0.5
STANDBY_P = 0.04

ALL_MODELS = [m["model_id"] for m in MACHINE_MODELS]
assert set(MODEL_HOURS) == set(ALL_MODELS), "cada modelo necesita su rango de horómetro"


def _models_of(*types: str) -> list[str]:
    return [m["model_id"] for m in MACHINE_MODELS if m["type"] in types]


# --------------------------------------------------------------------------- catálogo
# specialty usa el enum del OpenAPI: motor | hidraulica | electrica | neumaticos
CATALOG = [
    ("CMP-001", "Filtro de aceite de motor", "motor", ALL_MODELS, 45, 2),
    ("CMP-002", "Filtro de combustible", "motor", ALL_MODELS, 38, 2),
    ("CMP-003", "Filtro de aire primario", "motor", ALL_MODELS, 120, 3),
    ("CMP-004", "Inyector de combustible", "motor", ALL_MODELS, 650, 7),
    ("CMP-005", "Turbocompresor", "motor", ALL_MODELS, 4800, 21),
    ("CMP-006", "Bomba de agua", "motor", ALL_MODELS, 1200, 10),
    ("CMP-007", "Radiador", "motor", ALL_MODELS, 6500, 30),
    ("CMP-008", "Correa de accesorios", "motor", ALL_MODELS, 85, 3),
    (
        "CMP-009",
        "Bomba hidráulica principal",
        "hidraulica",
        _models_of("excavator", "loader", "bulldozer", "drill"),
        18500,
        35,
    ),
    ("CMP-010", "Cilindro hidráulico de brazo", "hidraulica", _models_of("excavator"), 9200, 28),
    ("CMP-011", "Manguera hidráulica de alta presión", "hidraulica", ALL_MODELS, 260, 4),
    ("CMP-012", "Kit de sellos de cilindro hidráulico", "hidraulica", ALL_MODELS, 340, 5),
    (
        "CMP-013",
        "Válvula de control hidráulico",
        "hidraulica",
        _models_of("excavator", "loader", "bulldozer", "drill"),
        5400,
        20,
    ),
    ("CMP-014", "Kit de rodamientos de motor", "motor", ALL_MODELS, 1350, 10),
    ("CMP-015", "Alternador", "electrica", ALL_MODELS, 1900, 12),
    ("CMP-016", "Motor de arranque", "electrica", ALL_MODELS, 1600, 12),
    ("CMP-017", "Batería 12 V servicio pesado", "electrica", ALL_MODELS, 320, 3),
    ("CMP-018", "Sensor de temperatura de refrigerante", "electrica", ALL_MODELS, 140, 4),
    ("CMP-019", "Sensor de vibración (acelerómetro)", "electrica", ALL_MODELS, 480, 7),
    ("CMP-020", "Módulo de control electrónico (ECU)", "electrica", ALL_MODELS, 7800, 30),
    ("CMP-021", "Neumático OTR 59/80R63", "neumaticos", _models_of("mining_truck"), 42000, 45),
    ("CMP-022", "Neumático OTR 45/65R45", "neumaticos", _models_of("loader"), 18000, 40),
    ("CMP-023", "Zapata de oruga", "neumaticos", _models_of("excavator", "bulldozer", "drill"), 650, 14),
    ("CMP-024", "Broca tricónica 10 5/8 in", "hidraulica", _models_of("drill"), 2900, 15),
    ("CMP-025", "Kit de discos de freno", "hidraulica", _models_of("mining_truck", "loader"), 2100, 10),
    # v4: repuestos específicos de los tipos/modelos nuevos (ninguno aplica al CAT-336 del golden path)
    ("CMP-026", "Cuchilla de hoja topadora", "hidraulica", _models_of("bulldozer"), 3800, 18),
    ("CMP-027", "Cuchilla de cucharón de cargador", "hidraulica", _models_of("loader"), 2400, 12),
    (
        "CMP-028",
        "Motor de tracción eléctrico de rueda",
        "electrica",
        ["KOM-930E", "LIE-T284", "BEL-75131"],
        65000,
        60,
    ),
    ("CMP-029", "Compresor de aire de perforación", "motor", _models_of("drill"), 14500, 25),
    ("CMP-030", "Rodillo inferior de tren de rodaje", "neumaticos", _models_of("bulldozer", "drill"), 980, 9),
]

# --------------------------------------------------------------------------- técnicos
# user_id = cognito:username del usuario demo (convención compartida con scripts/cognito_users.py)
TECHNICIANS = [
    ("TEC-01", "Ana Huamán", "norte", ["motor", "electrica"], "day"),
    ("TEC-02", "Luis Quispe", "sur", ["hidraulica", "motor"], "day"),
    ("TEC-03", "Rosa Condori", "este", ["electrica", "neumaticos"], "day"),
    ("TEC-04", "Carlos Mamani", "oeste", ["motor", "hidraulica"], "day"),
    ("TEC-05", "María Ccori", "norte", ["neumaticos", "hidraulica"], "night"),
    ("TEC-06", "Jorge Flores", "sur", ["electrica"], "night"),
    ("TEC-07", "Pedro Rojas", "norte", ["motor", "hidraulica"], "day"),
    ("TEC-08", "Lucía Vargas", "este", ["hidraulica", "motor"], "night"),
    ("TEC-09", "Miguel Chávez", "oeste", ["neumaticos", "electrica"], "night"),
    ("TEC-10", "Sofía Ramos", "sur", ["neumaticos", "motor"], "day"),
    ("TEC-11", "Diego Torres", "este", ["motor"], "day"),
    ("TEC-12", "Elena Paredes", "oeste", ["hidraulica", "electrica"], "day"),
    # v4: más cobertura nocturna y perfiles senior (3 especialidades). Ninguno en norte: el scoring del golden
    # path (contracts/fixtures/internal/scoring_response.json) compara contra TODOS los técnicos de norte.
    ("TEC-13", "Raúl Huanca", "sur", ["hidraulica", "neumaticos", "motor"], "night"),
    ("TEC-14", "Valeria Soto", "este", ["electrica", "motor"], "day"),
    ("TEC-15", "Óscar Cusi", "oeste", ["neumaticos"], "day"),
    ("TEC-16", "Gabriela Puma", "este", ["hidraulica", "electrica", "neumaticos"], "night"),
]

# Estado operativo inicial distinto de "disponible y sin carga" (v4). Solo técnicos fuera de norte (golden path).
# technician_id -> (available, current_load)
TECH_STATE_OVERRIDES = {
    "TEC-06": (False, 0),  # en capacitación
    "TEC-08": (True, 1),
    "TEC-11": (True, 2),
    "TEC-14": (True, 1),
    "TEC-15": (False, 0),  # descanso médico
}

# Ubicación inicial fijada para que el golden path sea determinista (contracts/fixtures/internal/scoring_*.json):
# para EX-023 (motor, high) gana TEC-07 (junto a WH-01) y el 2.º candidato es TEC-01 (rechazo -> reasignación).
PINNED_TECH_LOCATIONS = {
    "TEC-07": {"lat": -11.9150, "lon": -76.3965, "zone": "norte"},
    "TEC-01": {"lat": -11.9280, "lon": -76.4060, "zone": "norte"},
}

# --------------------------------------------------------------------------- notificaciones
# event_type = tabla "transición -> event_type" de contratos.md §10 (la usa notificar, B).
# Para event_type incident.*, la regla del rol `tecnico` notifica SOLO al técnico asignado (o al nuevo candidato).
# channels: push (FCM vía Pub/Sub), email (SNS alerts-{rol}),
# dashboard (sin envío: ya se ve por la réplica a Firestore).
# content_profile: technical (detalle) | operational (seguridad) | executive (impacto) -> lo usa notificar/ia-gemini
NOTIFICATION_RULES = [
    ("incident.detected", "operador", "high", ["push"], "operational", 10),
    ("incident.detected", "mantenimiento", "medium", ["email", "dashboard"], "technical", 15),
    ("incident.detected", "supervisor", "high", ["email", "dashboard"], "operational", 15),
    ("incident.detected", "gerencia", "critical", ["email"], "executive", 60),
    ("incident.assigned", "tecnico", "info", ["push", "email"], "technical", 0),
    ("incident.assigned", "mantenimiento", "medium", ["dashboard"], "technical", 0),
    ("incident.in_progress", "operador", "medium", ["push"], "operational", 0),
    ("incident.in_progress", "mantenimiento", "info", ["dashboard"], "technical", 0),
    ("incident.escalated", "tecnico", "info", ["push"], "technical", 5),
    ("incident.escalated", "mantenimiento", "low", ["email", "push"], "technical", 5),
    ("incident.escalated", "supervisor", "high", ["email"], "operational", 15),
    ("incident.resolved", "operador", "info", ["push"], "operational", 0),
    ("incident.resolved", "mantenimiento", "info", ["dashboard"], "technical", 0),
    ("incident.closed", "mantenimiento", "info", ["dashboard"], "technical", 0),
    ("incident.closed", "supervisor", "medium", ["dashboard"], "operational", 0),
    ("incident.closed", "gerencia", "critical", ["email"], "executive", 60),
    ("machine.silent", "mantenimiento", "low", ["dashboard", "email"], "technical", 30),
    ("machine.silent", "supervisor", "medium", ["dashboard"], "operational", 30),
    ("parts.shortage", "mantenimiento", "info", ["email"], "technical", 60),
    ("parts.shortage", "admin", "info", ["email"], "executive", 240),
    ("report.daily", "admin", "info", ["email"], "executive", 0),
    ("report.daily", "gerencia", "info", ["email"], "executive", 0),
]
NOTIFICATION_EVENT_TYPES = sorted({r[0] for r in NOTIFICATION_RULES})

# Ajustes de inventario para que la demo tenga alertas visibles: (warehouse, component) -> stock
INVENTORY_OVERRIDES = {
    ("WH-01", "CMP-014"): 2,  # justo en el mínimo: el golden path (EX-023, rodamiento) tiene stock
    ("WH-02", "CMP-021"): 0,  # low_stock: neumático de camión agotado en el sur
    ("WH-03", "CMP-005"): 0,  # low_stock: turbo agotado en el este
    ("WH-01", "CMP-008"): 60,  # overstock
    ("WH-03", "CMP-001"): 90,  # overstock
    # v4: más quiebres y sobrestock repartidos en los 4 almacenes
    ("WH-04", "CMP-009"): 0,  # low_stock: bomba hidráulica agotada en el oeste (zona de tractores)
    ("WH-04", "CMP-018"): 3,  # low_stock: sensores de temperatura bajo el mínimo
    ("WH-02", "CMP-028"): 0,  # low_stock: motor de tracción (lead time 60 días)
    ("WH-03", "CMP-029"): 0,  # low_stock: compresor de perforación agotado en la zona de perforación
    ("WH-01", "CMP-002"): 6,  # low_stock: filtros de combustible bajo el mínimo en el norte
    ("WH-02", "CMP-011"): 22,  # overstock: mangueras hidráulicas
    ("WH-04", "CMP-023"): 15,  # overstock: zapatas de oruga
    ("WH-03", "CMP-017"): 14,  # overstock: baterías
    ("WH-01", "CMP-021"): 1,  # en el mínimo: un solo neumático de camión en el norte
}


# =========================================================================== generadores
def _point_in_zone(rng: random.Random, zone: str) -> dict:
    cfg = ZONES[zone]
    angle = rng.uniform(0, 2 * math.pi)
    radius = cfg["radius_deg"] * math.sqrt(rng.random())
    lat = cfg["center"][0] + radius * math.sin(angle)
    lon = cfg["center"][1] + radius * math.cos(angle)
    return {"lat": round(lat, 6), "lon": round(lon, 6), "zone": zone}


# Supuesto de negocio (TAREA-11): costo del paro no planificado por hora según el tipo de equipo.
DOWNTIME_COST_USD_H = {
    "mining_truck": 1500,
    "excavator": 900,
    "drill": 1100,
    "loader": 800,
    "bulldozer": 700,
}


def build_machine_models() -> list[dict]:
    comps_by_model: dict[str, list[str]] = {m: [] for m in ALL_MODELS}
    for comp_id, _name, _spec, models, _cost, _lead in CATALOG:
        for m in models:
            comps_by_model[m].append(comp_id)
    out = []
    for m in MACHINE_MODELS:
        item = dict(m)
        item["component_ids"] = comps_by_model[m["model_id"]]
        item["downtime_cost_usd_h"] = DOWNTIME_COST_USD_H[m["type"]]
        out.append(item)
    return out


def _hours_for(rng: random.Random, model: str) -> float:
    lo, hi = MODEL_HOURS[model]
    return round(rng.triangular(lo, hi, lo + (hi - lo) * 0.45), 1)


def _health_for(rng: random.Random, hours: float, overdue: bool) -> int:
    """Salud inicial: baja con el horómetro y con el mantenimiento vencido (rango ~62-99)."""
    wear = min(hours / 32000, 1.0) * 18
    return max(62, min(99, round(rng.uniform(90, 99) - wear - (6 if overdue else 0))))


def _weighted_round_robin(weighted: list[tuple[str, int]], count: int) -> list[str]:
    """Reparto determinista y proporcional a los pesos (smooth weighted round-robin): todos los modelos aparecen."""
    current = {k: 0 for k, _ in weighted}
    total = sum(w for _, w in weighted)
    out = []
    for _ in range(count):
        for k, w in weighted:
            current[k] += w
        best = max(current, key=lambda k: current[k])
        current[best] -= total
        out.append(best)
    return out


def build_machines() -> list[dict]:
    rng = random.Random(RANDOM_SEED)
    machines = []
    for plan in FLEET_PLAN:
        model_seq = _weighted_round_robin(plan["models"], plan["count"])
        zones, zone_w = zip(*plan["zones"].items(), strict=True)
        for n in range(1, plan["count"] + 1):
            machine_id = f"{plan['prefix']}-{n:03d}"
            pinned = PINNED_MACHINES.get(machine_id, {})
            # Se sortea todo siempre (aunque esté fijada) para que fijar una máquina no altere al resto.
            model = pinned.get("model") or model_seq[n - 1]
            zone = pinned.get("zone") or rng.choices(zones, zone_w)[0]
            model_cfg = next(m for m in MACHINE_MODELS if m["model_id"] == model)
            interval = model_cfg["maintenance_interval_h"]
            # ~16 h de uso diario -> días hasta el próximo mantenimiento por horas
            interval_days = round(interval / 16)
            # ~8 % vencidas (raw >= OVERDUE_RAW_MIN, 2-6 días de atraso); el resto repartido dentro del ciclo.
            raw = rng.randint(3, 40)
            overdue = raw >= OVERDUE_RAW_MIN and machine_id not in PINNED_MACHINES
            if overdue:
                days_since = interval_days + (raw - OVERDUE_RAW_MIN + 1) * 2
            else:
                days_since = 1 + (min(raw, OVERDUE_RAW_MIN - 1) - 3) * (interval_days - 2) // (OVERDUE_RAW_MIN - 4)
            last_maint = REFERENCE_DATE - timedelta(days=days_since)
            next_maint = last_maint + timedelta(days=interval_days)
            location = _point_in_zone(rng, zone)
            hours = _hours_for(rng, model)
            health = _health_for(rng, hours, overdue)
            status_draw = rng.random()
            if overdue and status_draw < OVERDUE_IN_SHOP_P:
                status = "maintenance"  # entró al taller por el preventivo vencido
            elif status_draw > 1 - STANDBY_P:
                status = "stopped"  # equipo de reserva, detenido
            else:
                status = "operational"
            machines.append(
                {
                    "machine_id": machine_id,
                    "operation_id": OPERATION_ID,
                    "model": model,
                    "type": plan["type"],
                    "zone": zone,  # duplicado de location.zone para el GSI by_zone
                    "location": dict(pinned.get("location") or location),
                    "home_location": None,  # se completa abajo (igual a location inicial)
                    "status": pinned.get("status") or status,
                    "severity": "info",
                    "health_score": pinned.get("health_score") or health,
                    "last_seen_at": None,  # aún no hay telemetría (heartbeat debe ignorar null)
                    "expected_interval_s": EXPECTED_INTERVAL_S,
                    "operating_hours": pinned.get("operating_hours") or hours,
                    "last_maintenance_at": last_maint.isoformat(),
                    "next_maintenance_at": next_maint.isoformat(),
                    "failure_probability": None,
                    "rul_hours": None,
                    "open_incident_id": None,
                    "top_factors": [],
                    "model_version": None,
                    "seed_version": SEED_VERSION,
                }
            )
    for m in machines:
        m["home_location"] = dict(m["location"])
    return machines


def build_technicians() -> list[dict]:
    rng = random.Random(RANDOM_SEED + 1)
    techs = []
    for tech_id, name, zone, specialties, shift in TECHNICIANS:
        home_wh = next((w for w in WAREHOUSES if w["zone"] == zone), WAREHOUSES[0])
        location = _point_in_zone(rng, zone)  # se consume siempre, para no alterar la secuencia del resto
        location = dict(PINNED_TECH_LOCATIONS.get(tech_id, location))
        available, load = TECH_STATE_OVERRIDES.get(tech_id, (True, 0))
        techs.append(
            {
                "technician_id": tech_id,
                "user_id": f"u-tec-{tech_id.split('-')[1]}",
                "name": name,
                "zone": zone,
                "specialties": specialties,
                "location": location,
                "home_warehouse_id": home_wh["warehouse_id"],
                "available": available,
                "shift": shift,
                "current_load": load,
                "seed_version": SEED_VERSION,
            }
        )
    return techs


def build_catalog() -> list[dict]:
    return [
        {
            "component_id": cid,
            "name": name,
            "specialty": specialty,
            "compatible_models": models,
            "cost_usd": cost,  # nombre que lee la analítica de A (contratos.md §9)
            "lead_time_days": lead,
            "seed_version": SEED_VERSION,
        }
        for cid, name, specialty, models, cost, lead in CATALOG
    ]


def _stock_limits(unit_cost: float) -> tuple[int, int]:
    if unit_cost < 200:
        return 10, 40
    if unit_cost < 2000:
        return 2, 8
    if unit_cost < 10000:
        return 1, 4
    return 1, 2


def _alert(stock: int, smin: int, smax: int) -> str:
    if stock < smin:
        return "low_stock"
    if stock > smax:
        return "overstock"
    return "none"


def build_inventory() -> list[dict]:
    rng = random.Random(RANDOM_SEED + 2)
    items = []
    for wh in WAREHOUSES:
        for cid, name, _spec, _models, cost, _lead in CATALOG:
            smin, smax = _stock_limits(cost)
            stock = INVENTORY_OVERRIDES.get((wh["warehouse_id"], cid), rng.randint(smin, smax))
            items.append(
                {
                    "warehouse_id": wh["warehouse_id"],  # nombre del OpenAPI (InventoryItem)
                    "location_id": wh["warehouse_id"],  # nombre que lee A (contratos.md §9)
                    "warehouse_name": wh["name"],
                    "zone": wh["zone"],
                    "component_id": cid,
                    "name": name,
                    "stock": stock,
                    "stock_min": smin,
                    "stock_max": smax,
                    "alert": _alert(stock, smin, smax),
                    "seed_version": SEED_VERSION,
                }
            )
    return items


def build_notification_rules() -> list[dict]:
    return [
        {
            "event_type": event_type,
            "role": role,
            "severity_min": severity_min,
            "channels": channels,
            "content_profile": profile,
            "throttle_minutes": throttle,
            "enabled": True,
            "seed_version": SEED_VERSION,
        }
        for event_type, role, severity_min, channels, profile, throttle in NOTIFICATION_RULES
    ]


def build_all() -> dict[str, list[dict]]:
    """Todos los datasets. Las claves coinciden con las entradas de KEY_SCHEMA en seed.py."""
    return {
        "machines": build_machines(),
        "machine_models": build_machine_models(),
        "technicians": build_technicians(),
        "catalog": build_catalog(),
        "inventory": build_inventory(),
        "notification_rules": build_notification_rules(),
        "warehouses": [dict(w) for w in WAREHOUSES],
    }
