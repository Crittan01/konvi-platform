# Rev. 78 — Run E2E Certification (2026-04-30T03:01:51+00:00)

**Resumen**: ✅ PASS · 12/12 PASS · 0 FAIL · 0 SKIP

| # | Dominio | Status | Mensaje |
|---|---|---|---|
| 1 | Carrito + volumetría | ✅ PASS | 2 ítems resueltos (qtys=[2, 1]), peso total 0.350 kg |
| 2 | Soft-reserve | ✅ PASS | RPC F1 callable; 0 reservas activas, sin staleness |
| 3 | Captura + legal | ✅ PASS | Las 10 columnas de captura/legal existen en `contacts` |
| 4 | Wompi gateway | ✅ PASS | customer_data prepoblado con 6 campos válidos |
| 5 | RAG / KB | ✅ PASS | Cita de fuentes solo se inyecta cuando hay docs reales |
| 6 | UI / mensajería | ✅ PASS | 0 ghost messages en últimos 3 outbound text |
| 7 | Envia logística | ✅ PASS | EnviaClient expone 6 métodos requeridos (rates + label + tracking) |
| 8 | Multimodal | ✅ PASS | image_send_tool expone handler de petición de imagen |
| 9 | Coherencia validators | ✅ PASS | TS y Python coinciden en campos requeridos por building_type |
| 10 | Regex matrix | ✅ PASS | Document + phone validators pasan (3 válidos, 5 rechazados). HALLAZGO: ContactCreate.email solo tiene max_length=254 (sin regex) |
| 11 | Cart abandonment | ✅ PASS | 0 carts revisados, transiciones consistentes |
| 12 | Wompi events integrity | ✅ PASS | Sin eventos recientes (tabla vacía o nuevo deploy) |

### Evidencia D1 — Carrito + volumetría
```json
{
  "items_count": 2,
  "quantities": [
    2,
    1
  ],
  "total_weight_kg": 0.35
}
```

### Evidencia D2 — Soft-reserve
```json
{
  "active_total": 0,
  "rpc_callable": true
}
```

### Evidencia D3 — Captura + legal
```json
{
  "columns_verified": [
    "consent_given",
    "consent_given_at",
    "consent_text_version",
    "consent_revoked_at",
    "consent_evidence",
    "email",
    "document_type",
    "document_number",
    "address",
    "deleted_at"
  ]
}
```

### Evidencia D4 — Wompi gateway
```json
{
  "keys": [
    "email",
    "full_name",
    "legal_id",
    "legal_id_type",
    "phone_number",
    "phone_number_prefix"
  ]
}
```

### Evidencia D5 — RAG / KB
```json
{
  "real_doc_has_citation": true,
  "marker_only_skips": true
}
```

### Evidencia D6 — UI / mensajería
```json
{
  "sample_size": 3,
  "text_outbound": 3
}
```

### Evidencia D7 — Envia logística
```json
{
  "methods_present": [
    "get_rates",
    "generate_label",
    "track_shipments",
    "schedule_pickup",
    "cancel_shipment",
    "get_available_carriers"
  ]
}
```

### Evidencia D8 — Multimodal
```json
{
  "handler_present": true
}
```

### Evidencia D9 — Coherencia validators
```json
{
  "casa": [
    "city",
    "dane_code",
    "neighborhood",
    "state",
    "street"
  ],
  "edificio": [
    "apartment",
    "city",
    "dane_code",
    "neighborhood",
    "state",
    "street"
  ],
  "conjunto": [
    "apartment",
    "city",
    "dane_code",
    "neighborhood",
    "state",
    "street",
    "tower"
  ]
}
```

### Evidencia D10 — Regex matrix
```json
{
  "email_gap": "ContactCreate.email solo tiene max_length=254 (sin regex)",
  "phone_regex": "^\\+?[1-9]\\d{7,19}$"
}
```

### Evidencia D11 — Cart abandonment
```json
{
  "by_status": {},
  "sample_size": 0
}
```

### Evidencia D12 — Wompi events integrity
```json
{
  "sample_size": 0
}
```
