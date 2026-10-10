import subprocess
import unittest
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/"deploy"/"rocky"/"install-linux.sh"

class LinuxInstallerTests(unittest.TestCase):
    def run_installer(self,*args):
        return subprocess.run(["bash",str(SCRIPT),*args],capture_output=True,text=True)

    def test_detect_is_read_only(self):
        result=self.run_installer("--detect")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("Detected OS:",result.stdout)
        self.assertIn("Automated installation:",result.stdout)

    def test_help_is_read_only(self):
        result=self.run_installer("--help")
        self.assertEqual(result.returncode,0)
        self.assertIn("--confirm-new-vm",result.stdout)

    def test_bad_argument_rejected(self):
        result=self.run_installer("--unexpected-option")
        self.assertNotEqual(result.returncode,0)
        self.assertIn("Unknown argument",result.stderr)

if __name__=="__main__":
    unittest.main()
