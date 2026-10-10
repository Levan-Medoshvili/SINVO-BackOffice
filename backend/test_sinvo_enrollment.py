"""Offline contract tests for BackOffice enrollment; never call a real server."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sinvo_enrollment


class EnrollmentTests(unittest.TestCase):
    def test_identity_remains_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            first = sinvo_enrollment._identity_file(path)
            second = sinvo_enrollment._identity_file(path)
            self.assertEqual(first, second)
            self.assertEqual(len(first["installation_id"]), 36)
            self.assertGreaterEqual(len(first["credential"]), 48)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_first_run_registers_only_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def fake_request(endpoint, path, token=None, payload=None):
                calls.append((path, token, payload))
                if path.endswith("enrollment-status/"):
                    return 401, {}
                return 202, {"status": "pending_approval"}
            with patch.object(sinvo_enrollment, "_request", side_effect=fake_request):
                sinvo_enrollment.run("https://dev-updates.sinvo.ge", str(Path(directory) / "identity.json"), "Branch 1", "0.1.0")
            self.assertEqual(len(calls), 2)
            state = json.loads((Path(directory) / "identity.json").read_text())
            self.assertIsNone(calls[1][1])
            self.assertEqual(calls[1][2]["credential_sha256"], hashlib.sha256(state["credential"].encode()).hexdigest())
            self.assertNotIn(state["credential"], json.dumps(calls[1][2]))

    def test_pending_makes_no_heartbeat_or_download(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sinvo_enrollment, "_request", return_value=(200, {"status": "pending_approval"})) as request:
                sinvo_enrollment.run("https://dev-updates.sinvo.ge", str(Path(directory) / "identity.json"), "Branch 1", "0.1.0")
                self.assertEqual(request.call_count, 1)

    def test_heartbeat_includes_company_name(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sinvo_enrollment, "_request", side_effect=[
                (200, {"status": "approved"}),
                (200, {"status": "ok"}),
                (200, {"update_available": False, "release": None}),
            ]) as request:
                sinvo_enrollment.run("https://dev-updates.sinvo.ge",
                    str(Path(directory) / "identity.json"),
                    "SINVO BackOffice — DANI LLC", "0.1.0", company_name="DANI LLC")
                self.assertEqual(request.call_args_list[1].kwargs["payload"]["company_name"], "DANI LLC")

    def test_approved_checks_but_never_installs(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sinvo_enrollment, "_request", side_effect=[
                (200, {"status": "approved"}),
                (200, {"status": "ok"}),
                (200, {"update_available": True, "release": {"version": "0.2.0"}}),
            ]) as request:
                sinvo_enrollment.run("https://dev-updates.sinvo.ge", str(Path(directory) / "identity.json"), "Branch 1", "0.1.0")
                self.assertEqual(request.call_count, 3)


if __name__ == "__main__":
    unittest.main()
