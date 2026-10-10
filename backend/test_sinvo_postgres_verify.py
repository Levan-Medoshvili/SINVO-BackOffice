import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sinvo_postgres_verify import checked_name, isolated_name, ensure_backup_dir, verify_backup

class VerificationSafetyTests(unittest.TestCase):
    def test_unique_temp_name_and_identifier_validation(self):
        a,b=isolated_name(),isolated_name()
        self.assertNotEqual(a,b)
        self.assertTrue(a.startswith("sinvo_verify_"))
        self.assertEqual(checked_name("simplepos_erp"),"simplepos_erp")
        for bad in ("", "some-db", "postgres;DROP DATABASE", "x"*64, "name with spaces"):
            with self.assertRaises(ValueError):checked_name(bad)

    def test_private_backup_directory_required(self):
        with tempfile.TemporaryDirectory() as d:
            with patch("os.geteuid",return_value=0):
                with self.assertRaises(RuntimeError):verify_backup("simplepos_erp",d)
            Path(d,"private").mkdir(mode=0o700)
            with patch("os.geteuid",return_value=0),patch("pathlib.Path.stat") as stat:
                stat.return_value.st_uid=1000
                stat.return_value.st_mode=0o700
                with self.assertRaises(RuntimeError):ensure_backup_dir(Path(d,"private"))

    def test_bad_source_database_rejected_before_operation(self):
        with patch("os.geteuid",return_value=0):
            with self.assertRaises(ValueError):
                verify_backup("sinvo_verify_example","/nonexistent")
            with self.assertRaises(ValueError):
                verify_backup("test;dropdb","/nonexistent")

if __name__=="__main__":unittest.main()
