import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from arissto_sync.arissto import connection_string, source_connection, source_fingerprint
from arissto_sync.config import SourceConfig, load_settings, load_source_config


class ArisstoConnectionTests(unittest.TestCase):
    def config(self, **changes):
        values = {
            "server": "sql.example.test", "port": 1433, "database": "arissto",
            "user": "reader", "password": "pa$$word", "driver": "ODBC Driver 18 for SQL Server",
            "extra": "Encrypt=yes;TrustServerCertificate=yes;ApplicationIntent=ReadOnly",
            "connect_timeout": 15, "query_timeout": 30,
        }
        values.update(changes)
        return SourceConfig(**values)

    def test_connection_string_preserves_literal_dollar(self):
        value = connection_string(self.config())
        self.assertIn("PWD=pa$$word;", value)
        self.assertIn("ApplicationIntent=ReadOnly", value)

    def test_extra_cannot_override_credentials_or_server(self):
        with self.assertRaisesRegex(ValueError, "cannot override pwd"):
            connection_string(self.config(extra="Encrypt=yes;PWD=other"))

    def test_source_config_loads_without_fineract_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "ARISSTO_SERVER=sql.example.test\nARISSTO_DATABASE=arissto\n"
                "ARISSTO_USER=reader\nARISSTO_PASSWORD='pa$$word'\n",
                encoding="utf-8",
            )
            names = [name for name in os.environ if name.startswith("ARISSTO_") or name.startswith("FINERACT_")]
            with patch.dict(os.environ, {name: "" for name in names}, clear=False):
                config = load_source_config(str(env_file))
            self.assertEqual(config.password, "pa$$word")
            self.assertEqual(config.port, 1433)

    def test_target_specific_tls_settings_keep_production_strict(self):
        environment = {
            "ARISSTO_SERVER": "sql.example.test", "ARISSTO_DATABASE": "arissto",
            "ARISSTO_USER": "reader", "ARISSTO_PASSWORD": "secret",
            "FINERACT_LOCAL_API_URL": "https://localhost:8443/api/v1",
            "FINERACT_LOCAL_API_USER": "local", "FINERACT_LOCAL_API_PASSWORD": "secret",
            "FINERACT_LOCAL_EXPECTED_HOST": "localhost", "FINERACT_LOCAL_TLS_VERIFY": "false",
            "FINERACT_PROD_API_URL": "https://fineract.example.test/api/v1",
            "FINERACT_PROD_API_USER": "prod", "FINERACT_PROD_API_PASSWORD": "secret",
            "FINERACT_PROD_EXPECTED_HOST": "fineract.example.test", "FINERACT_PROD_TLS_VERIFY": "true",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertFalse(load_settings("local", "/dev/null").target.tls_verify)
            self.assertTrue(load_settings("prod", "/dev/null").target.tls_verify)

    def test_fingerprint_does_not_include_credentials(self):
        first = source_fingerprint(self.config(password="one", user="a"))
        second = source_fingerprint(self.config(password="two", user="b"))
        self.assertEqual(first, second)

    def test_read_only_mode_works_when_pyodbc_omits_symbolic_constant(self):
        connection = Mock()
        fake_pyodbc = SimpleNamespace(SQL_ATTR_ACCESS_MODE=101, connect=Mock(return_value=connection))
        with patch.dict("sys.modules", {"pyodbc": fake_pyodbc}):
            with source_connection(self.config()) as opened:
                self.assertIs(opened, connection)
        connection.set_attr.assert_called_once_with(101, 1)
        self.assertEqual(connection.timeout, 30)
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
