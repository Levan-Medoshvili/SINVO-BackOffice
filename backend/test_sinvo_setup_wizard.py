import unittest
import importlib.util
from pathlib import Path
path=Path(__file__).resolve().parents[1]/"deploy"/"rocky"/"setup_wizard.py"
spec=importlib.util.spec_from_file_location("setup_wizard",path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class WizardTests(unittest.TestCase):
    def test_valid_local(self):
        data={"company_name":"Example","identification_number":"123456789",
              "admin_username":"admin","admin_password":"sampleSecurePass123",
              "database_engine":"postgres","database_location":"local",
              "database_name":"simplepos_erp"}
        self.assertEqual(module.validate(data),[])
    def test_private_lan_address(self):
        self.assertEqual(module.private_address("10.0.110.160"), "10.0.110.160")
        with self.assertRaises(ValueError): module.private_address("127.0.0.1")
        with self.assertRaises(ValueError): module.private_address("169.254.3.1")

    def test_missing_company_id(self):
        self.assertTrue(module.validate({"company_name":"Example"}) )
    def test_remote_requires_credentials(self):
        data={"company_name":"Example","identification_number":"1234",
              "admin_username":"admin","admin_password":"sampleSecurePass123",
              "database_engine":"mssql","database_location":"remote",
              "database_name":"simplepos_erp","database_host":"10.0.0.5","database_port":"1433"}
        self.assertTrue(any("Remote database" in x for x in module.validate(data)))
