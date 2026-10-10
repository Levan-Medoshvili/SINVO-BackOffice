import tempfile
from pathlib import Path
import unittest
from sinvo_install_preflight import inspect_installation

class InstallPreflightTests(unittest.TestCase):
    def test_preflight_is_read_only_and_blocks_unsigned_install(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"pos"
            releases=root/"releases"
            (releases/"abc").mkdir(parents=True)
            (root/"current").symlink_to(releases/"abc",target_is_directory=True)
            env=Path(d)/"backend.env";env.write_text("TEST=yes")
            downloads=Path(d)/"downloads";downloads.mkdir(mode=0o700)
            result=inspect_installation(root,env,downloads,min_free_bytes=1)
            self.assertFalse(result["ready_to_install"])
            checks={c["code"]:c for c in result["checks"]}
            self.assertTrue(checks["release_layout"]["ok"])
            self.assertTrue(checks["config"]["ok"])
            self.assertTrue(checks["download_directory"]["ok"])
            self.assertFalse(checks["publisher_signature"]["ok"])
            self.assertFalse(checks["database_recovery"]["ok"])
            self.assertTrue((root/"current").is_symlink())

    def test_bad_layout_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            result=inspect_installation(Path(d)/"missing",Path(d)/"env",Path(d)/"missing")
            self.assertFalse(result["ready_to_install"])
            self.assertFalse(next(c for c in result["checks"] if c["code"]=="release_layout")["ok"])

if __name__=="__main__":unittest.main()
