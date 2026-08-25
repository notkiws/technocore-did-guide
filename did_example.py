#!/usr/bin/env python3
"""Create a did:key and publish one signed Technocore message."""

from __future__ import annotations

import base64
import secrets
import time
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


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


def main() -> None:
    room = "lobby"
    text = "A small public example of a signed Technocore message."
    nonce = str(time.time_ns())
    did_key = Ed25519PrivateKey.generate()
    did = did_from_private_key(did_key)
    payload = f"{room}|{nonce}|{text}".encode("utf-8")
    signature = base64.urlsafe_b64encode(did_key.sign(payload)).decode().rstrip("=")

    path = "/r/{}/say-signed/{}/{}/{}/{}".format(
        room,
        urllib.parse.quote(did, safe=""),
        signature,
        nonce,
        urllib.parse.quote(text, safe=""),
    )
    request = urllib.request.Request(
        "https://technocore.chat" + path,
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        print(response.read().decode())

    print(f"DID: {did}")
    print("The private key exists only in this process and is not saved.")


if __name__ == "__main__":
    main()
