#!/usr/bin/env python3
"""One-time publisher bootstrap, run by SINVO operations, never by customers.

Generates a private signing seed and publicly distributable Ed25519 key.
Private seed must be copied into a restricted Jenkins Secret Text credential.
This script never prints the secret to terminal.
"""
import base64
import os
from pathlib import Path
import sys
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 ci/bootstrap-signing.py /secure/offline/location")
    directory=Path(sys.argv[1])
    if directory.exists() and any(directory.iterdir()):
        raise SystemExit("Output directory is not empty; refusing overwrite")
    if directory.is_symlink():
        raise SystemExit("Refusing symlink directory")
    old_umask=os.umask(0o077)
    try:
        directory.mkdir(parents=True,mode=0o700,exist_ok=True)
        private=Ed25519PrivateKey.generate()
        seed=private.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())
        pub=private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        files={"staging-private-jenkins-secret.txt":base64.b64encode(seed)+b"\n",
               "staging-public-server.b64":base64.b64encode(pub)+b"\n",
               "staging-public-client.raw":pub}
        for name,data in files.items():
            flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0)
            fd=os.open(directory/name,flags,0o600 if "private" in name else 0o644)
            with os.fdopen(fd,"wb") as out:out.write(data)
        print("Signing pair generated. Install private seed as Jenkins Secret Text")
        print("credential ID sinvo-staging-signing-key; do not publish private seed.")
        print("Trust key ID staging-1 on server and BackOffice installer.")
    finally:
        os.umask(old_umask)

if __name__=="__main__":
    main()
