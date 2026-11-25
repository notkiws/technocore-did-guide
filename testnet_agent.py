#!/usr/bin/env python3
"""FLOP testnet agent steps that are plain HTTP: health, faucet claim, inference spend.

The official agent path on https://flop.finance/testnet/ is: create a DID **and a wallet**,
then purchase inference or transact with other agents on technocore.chat. A DID alone can
sign messages; it cannot pay. This script covers the paying half over HTTP:

  --doctor            what the public endpoints say right now (always safe)
  --faucet <SS58>     claim test FLOP for a wallet; add --claim to actually send it
  --infer             buy one inference from the gateway with a funded key

What still needs an sr25519 signer, and therefore the official CLI or a small Node script:
creating the SS58 wallet and signing the gateway enrollment challenge. See the README
section "Wallet and gateway enrollment" - the challenge is 8 fixed lines and the official
CLI aborts its enrollment POST after 10 seconds, which is why the manual flow is documented.

Never pass a mnemonic or private key to this script. The API key is read from
$FLOP_API_KEY so it does not land in shell history.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
OFFICIAL = ("flop.network", "flop.finance", "technocore.chat")

API = "https://api.flop.network"
FAUCET = "https://faucet.flop.network"
RPC = "https://rpc.devnet.flop.network"


def official(url: str) -> bool:
    host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    return any(host == d or host.endswith("." + d) for d in OFFICIAL)


def request(url: str, body: dict | None = None, headers: dict | None = None,
            timeout: int = 45) -> tuple[int | None, str]:
    """Refuse anything outside Flop's own domains: a signed request to the wrong host
    leaks a DID and a signature to a stranger."""
    if not official(url):
        return None, f"refused: {url} is not an official Flop domain"
    final = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        final.update(headers)
    data = None
    if body is not None:
        final["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=final,
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # network, DNS, TLS
        return None, f"{type(exc).__name__}: {exc}"


def show(label: str, status, body: str, limit: int = 300) -> None:
    print(f"{label:<22} HTTP {status}  {body[:limit]}")


def doctor(api: str, faucet: str) -> int:
    print("Public endpoint check (no keys, nothing spent)\n")
    status, body = request(api + "/health")
    show("gateway /health", status, body)
    if status == 200:
        try:
            net = json.loads(body).get("network") or {}
            print(f"{'':<22} network={net.get('network')} status={net.get('status')}")
        except Exception:
            pass

    status, body = request(api + "/v1/models")
    show("/v1/models", status, body)
    if status == 200:
        try:
            for model in json.loads(body).get("data", []):
                print(f"{'':<22} - {model.get('name') or model.get('id')}")
        except Exception:
            pass

    status, body = request(faucet + "/health")
    show("faucet /health", status, body)
    if status == 200:
        try:
            health = json.loads(body)
            print(f"{'':<22} ready={health.get('ready')} status={health.get('status')}")
        except Exception:
            pass

    status, body = request(RPC, body={"jsonrpc": "2.0", "id": 1,
                                      "method": "system_health", "params": []})
    show("rpc system_health", status, body)
    return 0


def faucet_claim(faucet: str, address: str, claim: bool) -> int:
    if not (address.startswith("5") and 47 <= len(address) <= 49):
        print(f"'{address}' does not look like an SS58 address (prefix 42, starts with 5).")
        return 2
    print(f"Wallet   : {address}")
    print(f"Faucet   : {faucet}")
    if not claim:
        print("Dry run. Add --claim to send the request. The faucet allows one grant per")
        print("address per 24h and caps grants per client IP.")
        return 0
    status, body = request(
        faucet + "/fund", body={"address": address},
        headers={"Origin": faucet, "Referer": faucet + "/"})
    show("POST /fund", status, body, 500)
    try:
        parsed = json.loads(body)
    except Exception:
        parsed = {}
    if parsed.get("success"):
        print(f"Granted {parsed.get('amount')} test FLOP, tx {parsed.get('txHash')}")
    elif parsed.get("reason"):
        print(f"Refused: {parsed.get('reason')}. Wait for the cooldown before retrying.")
    return 0 if parsed.get("success") else 1


def infer(api: str, model: str, prompt: str, max_tokens: int) -> int:
    key = os.environ.get("FLOP_API_KEY")
    if not key:
        print("Set FLOP_API_KEY first. Get one with the documented enrollment flow; the key")
        print("is a bearer token and must never be committed or pasted into a public room.")
        return 2
    print(f"Model    : {model}")
    print(f"Prompt   : {prompt}")
    status, body = request(
        api + "/v1/chat/completions",
        body={"model": model,
              "messages": [{"role": "user", "content": prompt}],
              "max_tokens": max_tokens},
        headers={"Authorization": "Bearer " + key}, timeout=120)
    show("POST completions", status, body, 600)
    if status != 200:
        print("402 means the key has no funded allowance. 429 'channel pool is full' and 503")
        print("'no admitted miner' mean network capacity, not a bad key.")
        return 1
    try:
        data = json.loads(body)
        print(f"{'':<22} usage={data.get('usage')}")
    except Exception:
        pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=API)
    parser.add_argument("--faucet", default=FAUCET)
    parser.add_argument("--doctor", action="store_true", help="check public endpoints")
    parser.add_argument("--address", metavar="SS58", help="wallet to fund")
    parser.add_argument("--claim", action="store_true", help="actually POST the faucet request")
    parser.add_argument("--infer", action="store_true", help="buy one inference")
    parser.add_argument("--model", default="qwen/qwen2.5-0.5b-instruct")
    parser.add_argument("--prompt", default="Explain in one sentence what paid inference is.")
    parser.add_argument("--max-tokens", type=int, default=64)
    args = parser.parse_args()

    for url in (args.api, args.faucet):
        if not official(url):
            sys.exit(f"Refusing non-official endpoint: {url}")

    if args.address:
        return faucet_claim(args.faucet, args.address, args.claim)
    if args.infer:
        return infer(args.api, args.model, args.prompt, args.max_tokens)
    return doctor(args.api, args.faucet)


if __name__ == "__main__":
    sys.exit(main())
