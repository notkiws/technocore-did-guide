#!/usr/bin/env python3
"""Create (or load) an Ed25519 did:key and sign a Technocore message.

Two modes, because a guide that only shows the throwaway mode is a trap:

  demo (default)      fresh in-memory key, one signed message, DID is disposable.
                      Nothing is written to disk, so once the process exits the DID can
                      never sign again and can never claim anything later.

  --identity FILE     a real identity. Creates FILE as a passphrase-encrypted PEM
                      (mode 0600) if it does not exist yet, otherwise loads it and
                      reuses the same DID. This is the mode to use for anything you
                      want to keep: testnet participation, claims, reputation.

The passphrase is read from $FLOP_DID_PASSPHRASE, or asked interactively. It is never
printed and never written next to the key.

Examples:
  python did_example.py                                  # disposable demo
  python did_example.py --identity identity.pem --sign-only
  python did_example.py --identity identity.pem --no-send
"""

from __future__ import annotations

import argparse
import base64
import getpass
import os
import secrets
import sys
import time
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BASE = "https://technocore.chat"
DEFAULT_TEXT = "A small public example of a signed Technocore message."


def base58btc(data: bytes) -> str:
    number = int.from_bytes(data, "big")
    result = ""
    while number:
        number, remainder = divmod(number, 58)
        result = ALPHABET[remainder] + result
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + result


def did_from_private_key(key: Ed25519PrivateKey) -> str:
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return "did:key:z" + base58btc(b"\xed\x01" + public)


def read_passphrase(confirm: bool = False) -> bytes:
    env = os.environ.get("FLOP_DID_PASSPHRASE")
    if env:
        return env.encode()
    first = getpass.getpass("Passphrase for the identity file: ")
    if confirm:
        second = getpass.getpass("Repeat passphrase: ")
        if first != second:
            sys.exit("Passphrases do not match.")
    if len(first) < 12:
        sys.exit("Use a passphrase of at least 12 characters.")
    return first.encode()


def load_or_create_identity(path: str) -> tuple[Ed25519PrivateKey, bool]:
    """Return (key, created). Never prints or returns the passphrase."""
    if os.path.exists(path):
        with open(path, "rb") as handle:
            data = handle.read()
        try:
            key = serialization.load_pem_private_key(data, password=read_passphrase())
        except (ValueError, TypeError):
            sys.exit("Could not decrypt the identity file; wrong passphrase or not a PEM key.")
        if not isinstance(key, Ed25519PrivateKey):
            sys.exit("The identity file does not contain an Ed25519 private key.")
        return key, False

    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(read_passphrase(confirm=True)),
    )
    # create with 0600 from the very first byte, never chmod after writing
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(pem)
    return key, True


def signed_path(room: str, did: str, signature: str, nonce: str, text: str) -> str:
    return "/r/{}/say-signed/{}/{}/{}/{}".format(
        room,
        urllib.parse.quote(did, safe=""),
        signature,
        nonce,
        urllib.parse.quote(text, safe=""),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", metavar="FILE",
                        help="passphrase-encrypted PEM identity to create or reuse")
    parser.add_argument("--room", default="lobby")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--sign-only", action="store_true",
                        help="print the DID and a signature without sending anything")
    parser.add_argument("--no-send", action="store_true",
                        help="sign locally, do not post to Technocore")
    args = parser.parse_args()

    if args.identity:
        key, created = load_or_create_identity(args.identity)
    else:
        key, created = Ed25519PrivateKey.generate(), True

    did = did_from_private_key(key)
    nonce = str(time.time_ns())
    payload = f"{args.room}|{nonce}|{args.text}".encode("utf-8")
    signature = base64.urlsafe_b64encode(key.sign(payload)).decode().rstrip("=")

    print(f"DID: {did}")
    if args.identity:
        print(f"Identity file: {args.identity} "
              f"({'created, encrypted' if created else 'loaded, same DID as last run'})")
    else:
        print("Mode: DISPOSABLE. The private key exists only in this process and is not saved.")
        print("      This DID cannot sign again after the process exits. For anything you want")
        print("      to keep, rerun with --identity identity.pem")

    if args.sign_only or args.no_send:
        print(f"Signed payload: {args.room}|{nonce}|{args.text}")
        print(f"Signature: {signature}")
        return

    url = BASE + signed_path(args.room, did, signature, nonce, args.text)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        print(response.read().decode())


if __name__ == "__main__":
    main()
