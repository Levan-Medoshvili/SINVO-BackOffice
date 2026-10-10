"""Verify Ed25519 signatures against a separately provisioned public key."""
import base64
import json
from pathlib import Path
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

FIELDS = {"product", "channel", "version", "sha256", "size", "notes", "key_id"}

def verify_manifest(release, trusted_key_id, trusted_public_key_file):
    manifest = release.get("manifest")
    signature = release.get("signature")
    if not isinstance(manifest, dict) or set(manifest) != FIELDS:
        raise RuntimeError("Signed release manifest missing or malformed")
    if not isinstance(signature, str) or not signature or release.get("signature_algorithm") != "ed25519":
        raise RuntimeError("Release has no trusted Ed25519 signature")
    if not trusted_key_id or manifest["key_id"] != trusted_key_id or release.get("signing_key_id") != trusted_key_id:
        raise RuntimeError("Release signing key identifier is not trusted")
    for key in ("product", "channel", "version", "sha256"):
        if manifest[key] != release.get(key):
            raise RuntimeError("Signed manifest does not match release metadata")
    if type(manifest["size"]) is not int or manifest["size"] != release.get("size"):
        raise RuntimeError("Signed manifest size differs")
    path = Path(trusted_public_key_file)
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("Out-of-band SINVO public key is missing")
    raw_key = path.read_bytes()
    if len(raw_key) != 32:
        raise RuntimeError("Expected a raw 32-byte Ed25519 public key")
    try:
        sig = base64.b64decode(signature, validate=True)
        if len(sig) != 64:
            raise ValueError("Invalid signature length")
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        Ed25519PublicKey.from_public_bytes(raw_key).verify(sig, canonical.encode("utf-8"))
    except (ValueError, InvalidSignature) as exc:
        raise RuntimeError("SINVO publisher signature validation failed") from exc
    return True
