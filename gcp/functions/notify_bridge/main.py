"""Cloud Function Gen2: Pub/Sub → FCM y Firestore actions → /bridge/events (RF-10.2, RF-16.5)."""


def on_notification(cloud_event):
    # TODO(RF-10.2): decodificar mensaje Pub/Sub y enviar push FCM
    raise NotImplementedError


def on_incident_action(cloud_event):
    # TODO(RF-16.5): reenviar la acción a POST /bridge/events con la API key de Secret Manager
    raise NotImplementedError
