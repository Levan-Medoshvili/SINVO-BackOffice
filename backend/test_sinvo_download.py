"""Offline tests: no network or database usage."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sinvo_enrollment
import sinvo_download

class VerifiedPackageTests(unittest.TestCase):
    def test_valid_download(self):
        data=b"test data"
        sha=hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            state=folder/"identity.json"
            sinvo_enrollment._identity_file(state)
            responses=[
                (200,{"status":"approved"}),
                (200,{"update_available":True,"release":{
                    "id":9,"size":len(data),"sha256":sha,"product":"backoffice",
                    "channel":"staging","version":"0.1.0+staging.9",
                    "download_path":"/api/v1/client/releases/9/download/"}})
            ]
            class Stream:
                status=200
                def __enter__(self): return self
                def __exit__(self,*args): pass
                def __init__(self,payload): self.payload=payload
                def read(self,n): p,self.payload=self.payload[:n],self.payload[n:];return p
            class Opener:
                def open(self,*a,**kw): return Stream(data)
            with patch.object(sinvo_download,"_request",side_effect=responses),patch.object(sinvo_download.urllib.request,"build_opener",return_value=Opener()):
                result=sinvo_download.download_verified("https://dev-updates.sinvo.ge",str(state),d)
            self.assertEqual(Path(result["file"]).read_bytes(),data)

    def test_hash_mismatch_removes_file(self):
        data=b"other"
        sha=hashlib.sha256(b"different").hexdigest()
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);state=folder/"identity.json"
            sinvo_enrollment._identity_file(state)
            responses=[(200,{"status":"approved"}),(200,{"update_available":True,"release":{
                "id":2,"size":len(data),"sha256":sha,"product":"backoffice",
                "channel":"staging","version":"1.0.0",
                "download_path":"/api/v1/client/releases/2/download/"}})]
            class Stream:
                status=200
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def __init__(self):self.remaining=data
                def read(self,n):p,self.remaining=self.remaining[:n],self.remaining[n:];return p
            class Opener:
                def open(self,*args,**kwargs):return Stream()
            with patch.object(sinvo_download,"_request",side_effect=responses),patch.object(sinvo_download.urllib.request,"build_opener",return_value=Opener()):
                with self.assertRaisesRegex(RuntimeError,"SHA-256"):
                    sinvo_download.download_verified("https://dev-updates.sinvo.ge",str(state),d)
            self.assertFalse(list(folder.glob("sinvo-backoffice-release-*.tar.gz")))

    def test_invalid_release_path_rejected_before_download(self):
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)/"identity.json"
            sinvo_enrollment._identity_file(state)
            responses=[(200,{"status":"approved"}),(200,{"update_available":True,"release":{
                "id":9,"size":5,"sha256":"a"*64,"product":"backoffice","channel":"staging",
                "download_path":"https://evil.example.org/steal"}})]
            with patch.object(sinvo_download,"_request",side_effect=responses):
                with self.assertRaisesRegex(RuntimeError,"metadata"):
                    sinvo_download.download_verified("https://dev-updates.sinvo.ge",str(state),d)

if __name__=="__main__": unittest.main()
