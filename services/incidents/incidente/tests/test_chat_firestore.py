"""chat_firestore: lectura REST del chat para summarize_chat (RF-15, RF-16.8)."""
import chat_firestore


def doc(**fields):
    def val(v):
        if v is None:
            return {"nullValue": None}
        if isinstance(v, str) and v.endswith("Z"):
            return {"timestampValue": v}
        return {"stringValue": v}

    return {"document": {"name": "x", "fields": {k: val(v) for k, v in fields.items()}}}


def test_lee_mensajes_en_orden_cronologico_y_descarta_sistema():
    calls = []

    def request(method, url, body, headers):
        calls.append((method, url, body, headers))
        return 200, [
            doc(author_id="u-mant-01", role="mantenimiento", text="¿Hay stock?", created_at="2026-11-14T10:02:00Z"),
            doc(author_id="sfn", role="sistema", text="Incidente asignado", created_at="2026-11-14T10:01:30Z"),
            doc(author_id="u-tec-07", role="tecnico", text="Llegué", quick_action="arrived",
                created_at="2026-11-14T10:01:00Z"),
            {"readTime": "2026-11-14T10:03:00Z"},
        ]

    chat = chat_firestore.FirestoreChat("arquifusion-g27", lambda: "TOKEN", request)
    msgs = chat.messages("INC-01JC8ZK")

    assert [m["text"] for m in msgs] == ["Llegué", "¿Hay stock?"]
    assert msgs[0] == {
        "author_id": "u-tec-07",
        "role": "tecnico",
        "text": "Llegué",
        "quick_action": "arrived",
        "created_at": "2026-11-14T10:01:00Z",
    }
    method, url, body, headers = calls[0]
    assert method == "POST"
    assert url.endswith("/projects/arquifusion-g27/databases/(default)/documents/incidents/INC-01JC8ZK:runQuery")
    assert body["structuredQuery"]["from"] == [{"collectionId": "messages"}]
    assert body["structuredQuery"]["limit"] == chat_firestore.MAX_MESSAGES
    assert headers == {"Authorization": "Bearer TOKEN"}


def test_error_http_lanza():
    chat = chat_firestore.FirestoreChat("p", lambda: "T", lambda *a: (403, {"error": {}}))
    try:
        chat.messages("INC-1")
    except RuntimeError as exc:
        assert "403" in str(exc)
    else:
        raise AssertionError("debía fallar")


def test_texto_largo_se_trunca_y_vacios_se_omiten():
    assert chat_firestore.to_message({"text": {"stringValue": "  "}, "role": {"stringValue": "tecnico"}}) is None
    m = chat_firestore.to_message({"text": {"stringValue": "a" * 5000}, "role": {"stringValue": "tecnico"}})
    assert len(m["text"]) == chat_firestore.MAX_TEXT
