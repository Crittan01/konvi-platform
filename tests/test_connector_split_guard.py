"""Guard anti-drift del manifest CONNECTOR_OWNED (split de venv por dominio de pins).

Si alguien agrega/renombra un test connector-only sin actualizar
connector_manifest.CONNECTOR_OWNED, este test FALLA — así el manifest no se desincroniza
en silencio y ningún connector-test corre en el leg equivocado (bajo la versión de fastapi
errónea). Es dep-free (solo lee fuente) → corre en el leg core. Ver tests/conftest.py.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from connector_manifest import CONNECTOR_OWNED, connector_only_by_scan  # noqa: E402


class ConnectorManifestGuardTests(unittest.TestCase):
    def test_manifest_no_drift(self):
        detected = connector_only_by_scan()
        faltan = detected - CONNECTOR_OWNED
        sobran = CONNECTOR_OWNED - detected
        self.assertFalse(
            faltan,
            f"tests connector-only SIN registrar (agregalos a CONNECTOR_OWNED en "
            f"tests/connector_manifest.py): {sorted(faltan)}",
        )
        self.assertFalse(
            sobran,
            f"CONNECTOR_OWNED lista archivos que ya no son connector-only (quitalos): "
            f"{sorted(sobran)}",
        )


if __name__ == "__main__":
    unittest.main()
