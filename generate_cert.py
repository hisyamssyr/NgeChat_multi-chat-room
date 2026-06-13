"""Generate a local self-signed TLS certificate for NgeChat.

The server expects:
  certs/cert.pem
  certs/key.pem

This helper calls the OpenSSL executable if it is available on PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def main() -> int:
    openssl = shutil.which("openssl")
    if not openssl:
        print("OpenSSL was not found on PATH.")
        print("Install OpenSSL, or create certs/cert.pem and certs/key.pem manually.")
        return 1

    base_dir = os.path.dirname(os.path.abspath(__file__))
    cert_dir = os.path.join(base_dir, "certs")
    cert_path = os.path.join(cert_dir, "cert.pem")
    key_path = os.path.join(cert_dir, "key.pem")
    os.makedirs(cert_dir, exist_ok=True)

    cmd = [
        openssl,
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-keyout",
        key_path,
        "-out",
        cert_path,
        "-days",
        "365",
        "-nodes",
        "-subj",
        "/CN=localhost",
    ]
    print("Generating self-signed certificate...")
    subprocess.run(cmd, check=True)
    print(f"Created {cert_path}")
    print(f"Created {key_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
