"""Chain writer: writes a stored log entry, masked text included, to our LLMVerificationV2 contract on Ethereum Sepolia.

A person reads the entry and presses Permit before anything is sent. The contract keeps the entry as canonical JSON (record)
and its SHA-256 (entry_hash), so anyone can check that the text on chain matches its hash (lookup).
Needs PRIVATE_KEY of a Sepolia test wallet in experiments/.env; without it, writing is off and lookups still work.

Self-test, no network: python mvp/chain.py
"""
import hashlib
import json
import os

RPC = os.environ.get("SEPOLIA_RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com")
CONTRACT = os.environ.get("CONTRACT_ADDRESS", "0xF11A5C310Db05ADC4C4f8cb88b144bA900Fe0843")
EXPLORER = "https://sepolia.etherscan.io"
CHAIN_ID = 11155111
ABI = [
    {"name": "storeRecord", "type": "function", "stateMutability": "nonpayable", "outputs": [],
     "inputs": [{"name": "contentHash", "type": "bytes32"}, {"name": "ipfsCID", "type": "string"}, {"name": "consensusVotes", "type": "string"}]},
    {"name": "getRecord", "type": "function", "stateMutability": "view", "inputs": [{"name": "contentHash", "type": "bytes32"}],
     "outputs": [{"name": "exists", "type": "bool"}, {"name": "ipfsCID", "type": "string"}, {"name": "consensusVotes", "type": "string"},
                 {"name": "submitter", "type": "address"}, {"name": "timestamp", "type": "uint256"}]},
]
NO_IPFS = "none"  # the contract needs a non-empty CID; the text is not published on IPFS
_w3 = None


def _key():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "experiments", ".env"))
    return os.environ.get("PRIVATE_KEY", "")


def ready():
    return bool(_key())


def record(entry):
    """What goes on chain: the log entry as canonical JSON (sorted keys, no spaces), without the raw-record hash,
    which together with the masked text would let anyone test guesses for a masked value."""
    return json.dumps({k: v for k, v in entry.items() if k != "hash"}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def entry_hash(entry):
    return "0x" + hashlib.sha256(record(entry).encode()).hexdigest()


def tx_url(tx):
    return f"{EXPLORER}/tx/{tx}"


def _contract():
    global _w3
    from web3 import Web3
    if _w3 is None:
        _w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 20}))
    return _w3, _w3.eth.contract(address=Web3.to_checksum_address(CONTRACT), abi=ABI)


def lookup(content_hash):
    """What the contract holds for a hash: None, or {record, submitter, time}."""
    _, c = _contract()
    exists, _cid, rec, who, ts = c.functions.getRecord(content_hash).call()
    return {"record": rec, "submitter": who, "time": ts} if exists else None


def anchor(entry):
    """Sends storeRecord for one log entry and returns {"content_hash", "tx", "url"} once the node accepts it.
    Raises ValueError if the hash is already on chain (the contract would revert)."""
    from eth_account import Account
    w3, c = _contract()
    h = entry_hash(entry)
    if lookup(h):
        raise ValueError(f"already on chain: {h}")
    acct = Account.from_key(_key())
    tx = c.functions.storeRecord(h, NO_IPFS, record(entry)).build_transaction(
        {"from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address, "pending"), "chainId": CHAIN_ID})
    sent = w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction).to_0x_hex()
    return {"content_hash": h, "tx": sent, "url": tx_url(sent)}


def status(tx):
    """pending, confirmed or failed."""
    w3, _ = _contract()
    from web3.exceptions import TransactionNotFound
    try:
        return "confirmed" if w3.eth.get_transaction_receipt(tx)["status"] == 1 else "failed"
    except TransactionNotFound:  # the public node drops old receipts; a mined transaction still has a block number
        try:
            return "confirmed" if w3.eth.get_transaction(tx).get("blockNumber") else "pending"
        except TransactionNotFound:
            return "pending"


if __name__ == "__main__":
    e = {"time": "2026-11-13T14:12:43", "hash": "ab12", "status": "stored", "masked": "User: hi", "masks": 0, "app": "care", "category": None}
    assert entry_hash(e) == entry_hash(dict(reversed(list(e.items()))))  # key order does not matter
    assert entry_hash(e) != entry_hash({**e, "masked": "User: hi!"}) and len(entry_hash(e)) == 66
    assert record(e) == '{"app":"care","category":null,"masked":"User: hi","masks":0,"status":"stored","time":"2026-11-13T14:12:43"}'
    assert entry_hash(e) == "0x" + hashlib.sha256(record(e).encode()).hexdigest()
    print("ok")
