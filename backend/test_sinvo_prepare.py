import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sinvo_prepare import save_progress, prepare

class PreparationTests(unittest.TestCase):
    def test_progress_file_and_sanitized_state(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"progress.json"
            save_progress(path,"downloading",54,"Downloading")
            content=json.loads(path.read_text())
            self.assertEqual(content["percent"],54)
            self.assertEqual(content["stage"],"downloading")
            self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_success_marks_verified_without_installation(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/"progress.json")
            with patch("sinvo_prepare.download_verified",return_value={"version":"0.1.0+staging.23"}) as verify:
                prepare("https://dev-updates.sinvo.ge","identity",d,path)
            self.assertEqual(json.loads(Path(path).read_text())["stage"],"ready")
            self.assertEqual(verify.call_count,1)

    def test_failure_is_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/"progress.json")
            with patch("sinvo_prepare.download_verified",side_effect=RuntimeError("unavailable")):
                with self.assertRaises(RuntimeError):
                    prepare("https://dev-updates.sinvo.ge","identity",d,path)
            self.assertEqual(json.loads(Path(path).read_text())["stage"],"failed")

if __name__=="__main__": unittest.main()
