"""Rev. 96 — Tests de tokenización document_number.

Cobertura:
  • Helpers Python (normalize/hash/last4/mask).
  • Migración SQL: columnas, trigger, función fn_document_hash.
  • Coherencia entre Python y SQL: mismo input produce mismo hash en
    ambos lados (test indirecto vía regex equivalence).
"""
import os
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from lib.pii_tokenize import (  # noqa: E402
    normalize_document,
    document_hash,
    document_last4,
    mask_document,
)

MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..",
    "supabase/migrations/20260506010000_pii_tokenization.sql"
)


class NormalizeDocumentTests(unittest.TestCase):

    def test_strips_spaces_dashes_dots(self):
        self.assertEqual(normalize_document("123-456.789"), "123456789")
        self.assertEqual(normalize_document("123 456 789"), "123456789")
        self.assertEqual(normalize_document("12.345-678"), "12345678")

    def test_uppercases(self):
        self.assertEqual(normalize_document("ce 1.234.567"), "CE1234567")

    def test_none_returns_none(self):
        self.assertIsNone(normalize_document(None))
        self.assertIsNone(normalize_document(""))
        self.assertIsNone(normalize_document("   "))

    def test_idempotent(self):
        # normalize(normalize(x)) == normalize(x)
        s = "1.234-567 89"
        self.assertEqual(normalize_document(normalize_document(s)),
                         normalize_document(s))


class DocumentHashTests(unittest.TestCase):

    def test_hash_is_64_chars(self):
        h = document_hash("1234567890")
        self.assertEqual(len(h), 64)

    def test_hash_is_deterministic(self):
        self.assertEqual(document_hash("123-456"), document_hash("123-456"))

    def test_format_independent_hash(self):
        # Distintos formatos del mismo doc → mismo hash.
        h1 = document_hash("12345678")
        h2 = document_hash("12.345.678")
        h3 = document_hash("1234-5678")
        h4 = document_hash("12 34 56 78")
        self.assertEqual(h1, h2)
        self.assertEqual(h2, h3)
        self.assertEqual(h3, h4)

    def test_none_returns_none(self):
        self.assertIsNone(document_hash(None))
        self.assertIsNone(document_hash(""))

    def test_known_vector(self):
        # Hash determinístico esperado para "12345678" normalizado.
        # sha256("12345678").hexdigest()[:16]
        h = document_hash("12345678")
        self.assertTrue(h.startswith("ef797c8118f02dfb"))


class DocumentLast4Tests(unittest.TestCase):

    def test_returns_last_four_chars(self):
        self.assertEqual(document_last4("1234567890"), "7890")

    def test_strips_separators(self):
        self.assertEqual(document_last4("12-34.56"), "3456")

    def test_short_doc_returns_full(self):
        self.assertEqual(document_last4("12"), "12")

    def test_none_returns_none(self):
        self.assertIsNone(document_last4(None))


class MaskDocumentTests(unittest.TestCase):

    def test_returns_masked_with_last4(self):
        self.assertEqual(mask_document("1234567890"), "****7890")

    def test_short_doc_pads(self):
        self.assertEqual(mask_document("99"), "****99")

    def test_none_returns_none(self):
        self.assertIsNone(mask_document(None))


class MigrationStructureTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(MIGRATION_PATH, encoding="utf-8") as f:
            cls.sql = f.read()
        cls.sql_lower = cls.sql.lower()

    def test_adds_hash_and_last4_columns(self):
        self.assertIn("document_number_hash", self.sql_lower)
        self.assertIn("document_number_last4", self.sql_lower)

    def test_columns_are_additive_not_destructive(self):
        # NO debe haber DROP COLUMN document_number.
        self.assertNotIn("drop column document_number", self.sql_lower)

    def test_creates_hash_function(self):
        self.assertIn("fn_document_hash", self.sql_lower)

    def test_creates_last4_function(self):
        self.assertIn("fn_document_last4", self.sql_lower)

    def test_uses_sha256(self):
        self.assertIn("sha256", self.sql_lower)

    def test_creates_sync_trigger(self):
        self.assertIn("trg_sync_document_derived", self.sql_lower)

    def test_trigger_runs_before_insert_or_update(self):
        self.assertRegex(
            self.sql,
            r"BEFORE\s+INSERT\s+OR\s+UPDATE",
        )

    def test_includes_backfill_for_existing_rows(self):
        # Backfill UPDATE para rows con document_number ya existente.
        self.assertRegex(
            self.sql,
            r"UPDATE\s+public\.contacts\s+SET\s+document_number_hash",
        )

    def test_index_on_hash_for_lookup(self):
        self.assertIn("idx_contacts_document_number_hash", self.sql_lower)

    def test_last4_check_constraint_max_4(self):
        # last4 debe tener CHECK length <= 4.
        self.assertRegex(
            self.sql,
            r"LENGTH\(document_number_last4\)\s*<=\s*4",
        )


class PythonSqlCoherenceTests(unittest.TestCase):
    """Validación que normalize_document coincide en regla con la migración SQL."""

    @classmethod
    def setUpClass(cls):
        with open(MIGRATION_PATH, encoding="utf-8") as f:
            cls.sql = f.read()

    def test_sql_uses_same_separators_as_python(self):
        # Python usa [\s\-\.]. SQL debe usar la misma regex.
        self.assertIn(r"'[\s\-\.]'", self.sql)

    def test_sql_uppercases_like_python(self):
        # Tanto Python (.upper()) como SQL (upper(...)) deben aplicar uppercase.
        self.assertRegex(self.sql, r"upper\(regexp_replace")


if __name__ == "__main__":
    unittest.main()
