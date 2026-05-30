# Deuda de tests pre-existentes (9 fallos)

**Fecha:** 2026-05-29.
**Branch:** `refactor/inbox-components`.
**Contexto:** detectados durante UAT exhaustivo post-refactor 10/10.

NO son regresión del refactor del Inbox. Son tests escritos para una versión ANTERIOR del código (rev107 o anteriores) cuyo contrato cambió posteriormente. Los tests apuntan a APIs/símbolos/comportamientos que ya no existen o cambiaron sus reglas.

## Inventario (9 tests fallidos)

### 1. `tests/test_kb_tool_embeddings.py` (2 fallos)

```
tests/test_kb_tool_embeddings.py::KbToolEmbeddingsTests::test_embed_query_retries_with_fallback_on_404
tests/test_kb_tool_embeddings.py::KbToolEmbeddingsTests::test_embed_query_uses_primary_model
```

**Causa**: el test hace `patch.object(kb_tool, "GEMINI_EMBEDDING_MODEL", ...)` pero esa constante ya NO existe en `kb_tool.py`. La función `_embed_query_vector` delega a `llm_embed.embed_with_cascade` que maneja modelo internamente.

**Fix correcto**: reescribir tests para mockear `embed_with_cascade` (la nueva abstracción), no la constante deprecada.

**Esfuerzo**: ~30 min.

### 2. `tests/agentic/test_invariant_empty_promise.py` (2 fallos)

```
test_estoy_calculando_con_quote_shipping_ok
test_un_momento_pero_con_list_catalog_ok
```

**Causa probable**: el invariant `EmptyPromiseInvariant` fue refinado entre rev107 y rev109 — la lista de "tools válidos para cubrir la promesa" cambió. Los tests asumen que `quote_shipping`/`list_catalog` cubren ciertas promesas que ahora ya no son aceptadas (o viceversa).

**Fix correcto**: re-leer el contrato actual del invariant + ajustar el fixture del test.

**Esfuerzo**: ~30-40 min.

### 3. `tests/agentic/test_invariant_pii_coherence.py` (3 fallos)

```
test_name_coherente_ok
test_name_mismatch_rewrite
test_tildes_match_flexible
```

**Causa probable**: `PIICoherenceInvariant` fue evolucionado — probablemente sumando matching flexible para variantes de nombre (apóstrofes, mayúsculas, tildes). Los tests fueron escritos para la versión strict inicial.

**Fix correcto**: actualizar fixtures con los casos canónicos actuales.

**Esfuerzo**: ~30 min.

### 4. `tests/agentic/test_select_carrier_db_first.py` (4 fallos)

```
test_carrier_name_only_resuelve_sin_rate_id_rev107
test_db_options_resuelven_rate_id_sin_ctx_extras
test_fuzzy_match_carrier_name_resuelve_rate_id_inventado
test_fuzzy_match_normaliza_separadores_underscore_vs_espacio
```

**Causa**: error visible — los tests esperan que `select_carrier_for_cart` resuelva por nombre fuzzy. Pero el código actual retorna `CARRIER_SELECTION_NOT_EXPLICIT` con mensaje *"NO selecciones carrier sin que el cliente lo nombre explícitamente"*.

Esto sugiere que el contrato cambió: en algún punto post-rev107 se añadió una **validación stricter** que requiere selección explícita del cliente (probablemente para evitar bot inventando carriers). Los tests reflejan el comportamiento ANTIGUO.

**Fix correcto**: decidir si la validación stricter es la correcta (probablemente sí, para alinear con principio A.0.1 "LLM no decide verdad transaccional") y actualizar los tests para reflejar el nuevo contrato — o validar que el comportamiento fuzzy es deseable cuando hay match alto-confidence y relajar la validación.

**Esfuerzo**: ~1h (requiere decisión arquitectónica + ajustar tests + posiblemente lógica).

## Recomendación

Sesión dedicada de **~2-3 horas** para:
1. Cleanup tests 1-3 (3 archivos, ~1.5h) — son simples ajustes de mock/fixture.
2. Decisión arquitectónica + cleanup tests 4 (~1h) — requiere alineación con principio A.0.1.

**NO marcar como skip** sin tracking — esconde el problema. La documentación de este doc + git issue/PR es suficiente para no perderlos de vista.

## Workaround para CI

Mientras tanto, `validate.sh` marca "1 ERROR" por estos tests. Si necesitan green CI urgente, opciones:

1. **Skip explícito con TODO**:
   ```python
   import pytest
   @pytest.mark.skip(reason="Deuda técnica — ver docs/refactor/0004-test-debt-pre-existing.md")
   ```

2. **Marker xfail**:
   ```python
   @pytest.mark.xfail(reason="Pre-existing — contrato del código cambió post-rev107", strict=False)
   ```

3. **Excluir vía env**:
   ```bash
   pytest tests/ --ignore=tests/agentic/test_invariant_empty_promise.py ...
   ```

Recomendado: **xfail con razón clara**. Documenta el problema sin esconderlo, y al arreglarlo el test pasa naturalmente.

## Histórico

- **Detectados**: 2026-05-29 durante UAT exhaustivo de la sesión refactor 10/10.
- **NO introducidos por el refactor del Inbox** (verificado via `git diff phase-2-agentic-rewrite..HEAD tests/` → solo `test_db_persistence_reopen.py` modificado).
- **Origen**: rev107 + cambios posteriores (`empty_promise_invariant`, `pii_coherence`, `select_carrier_db_first` agregados en rev107 según `git log`).
