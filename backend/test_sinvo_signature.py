import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sinvo_signature import verify_manifest

class PublisherSignatureTests(unittest.TestCase):
    def setUp(self):
        self.private=Ed25519PrivateKey.generate()
        self.manifest={"product":"backoffice","channel":"staging","version":"1.0.0",
            "sha256":hashlib.sha256(b"artifact").hexdigest(),"size":8,
            "notes":"Signed release","key_id":"staging-test"}
        self.release={**{k:self.manifest[k] for k in ("product","channel","version","sha256")},
            "size":8,"manifest":self.manifest,"signing_key_id":"staging-test",
            "signature_algorithm":"ed25519"}
        self.sign()
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.key=Path(self.directory.name)/"trusted.raw"
        self.key.write_bytes(self.private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,format=serialization.PublicFormat.Raw))

    def sign(self):
        canonical=json.dumps(self.manifest,sort_keys=True,separators=(",",":"),ensure_ascii=False)
        self.release["signature"]=base64.b64encode(self.private.sign(canonical.encode())).decode()

    def test_valid_signature(self):
        self.assertTrue(verify_manifest(self.release,"staging-test",self.key))

    def test_tampered_metadata_rejected(self):
        self.release["size"]=9
        with self.assertRaises(RuntimeError):verify_manifest(self.release,"staging-test",self.key)

    def test_tampered_manifest_rejected(self):
        self.manifest["notes"]="Tampered"
        with self.assertRaises(RuntimeError):verify_manifest(self.release,"staging-test",self.key)

    def test_wrong_key_or_id_rejected(self):
        with self.assertRaises(RuntimeError):verify_manifest(self.release,"wrong",self.key)
        self.key.write_bytes(Ed25519PrivateKey.generate().public_key().public_bytes(
            encoding=serialization.Encoding.Raw,format=serialization.PublicFormat.Raw))
        with self.assertRaises(RuntimeError):verify_manifest(self.release,"staging-test",self.key)

    def test_missing_signature_rejected(self):
        self.release["signature"]=""
        with self.assertRaises(RuntimeError):verify_manifest(self.release,"staging-test",self.key)

if __name__=="__main__":unittest.main()
