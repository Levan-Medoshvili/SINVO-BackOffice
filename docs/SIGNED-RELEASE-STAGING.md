# Ed25519 signed release staging setup

The Update Server supports signed release publishing, including a pinned
public signing key and a key identifier. Signed release discovery now carries
the canonical manifest, Ed25519 signature, and key identifier.

The BackOffice client accepts:
```
python sinvo_download.py --directory PRIVATE_DIR --require-signature \
  --key-id staging-1 \
  --public-key /etc/pos-erp/sinvo-signing-public.raw
```
The public key must be raw 32-byte Ed25519, installed via a separately
trusted channel (not downloaded from the update service).

The BackOffice publisher accepts optional environment variables:
- SINVO_SIGNING_PRIVATE_KEY_B64: base64 of raw 32-byte Ed25519 seed
- SINVO_SIGNING_KEY_ID: e.g. staging-1

To activate signing, configure **both** the Jenkins publisher and Update
Server before enabling SINVO_REQUIRE_SIGNATURES=1. The current Jenkinsfile
does not inject signing credentials: publisher continues to publish unsigned
Staging packages until its administrator wires an appropriately scoped secret.
Never commit, echo, or paste a private key.

On Update Server configure matching SINVO_SIGNING_PUBLIC_KEY (base64 of
the raw 32-byte public key), SINVO_SIGNING_KEY_ID, and when ready,
SINVO_REQUIRE_SIGNATURES=1. Reconfigure the server and Jenkins deployment
separately, and do not turn on mandatory signatures before the publisher
secret is configured and verified.

Unsigned historical packages are still eligible for manual download in
development mode, but DO NOT meet the requirements for installation.
Signature verification is intentionally explicit and will fail closed when
--require-signature is used. No automatic update activation is provided yet.
