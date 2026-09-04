"""Tests for blockchain client logic, live Hardhat integration, and error handling."""

import os
import uuid
import hashlib
from blockchain.client import BlockchainClient, BlockchainError
from fingerprint.canonical import to_bytes32_hex

def test_to_bytes32_hex_conversion():
    raw_hash = "11223344556677889900aabbccddeeff11223344556677889900aabbccddeeff"
    b32 = to_bytes32_hex(raw_hash)
    assert b32 == "0x11223344556677889900aabbccddeeff11223344556677889900aabbccddeeff"

def test_blockchain_offline_handling():
    # Use invalid RPC port to test graceful offline failure
    client = BlockchainClient(rpc_url="http://127.0.0.1:99999")
    assert client.is_connected() is False

def test_live_blockchain_record_and_verify():
    client = BlockchainClient()
    if not client.is_connected() or not client.contract:
        return  # Skip if node not running

    # Generate a random unique test hash
    unique_data = f"test_provenance_{uuid.uuid4()}".encode("utf-8")
    test_hash = hashlib.sha256(unique_data).hexdigest()

    # Verify does not exist initially
    init_check = client.verify_provenance(test_hash)
    assert init_check["exists"] is False

    # Record onto smart contract
    tx = client.record_provenance(test_hash)
    assert tx["status"] == "SUCCESS"
    assert tx["transaction_hash"].startswith("0x")
    assert tx["block_number"] > 0

    # Query verify again
    post_check = client.verify_provenance(test_hash)
    assert post_check["exists"] is True
    assert post_check["timestamp"] > 0
    assert post_check["recorder"].lower() == client.get_default_account().lower()


def test_safe_offline_provenance_ledger():
    client = BlockchainClient(rpc_url="http://127.0.0.1:99999")
    assert client.is_connected() is False

    test_hash = hashlib.sha256(f"offline_test_{uuid.uuid4()}".encode("utf-8")).hexdigest()
    # Before recording, check should be False
    pre = client.verify_provenance_safe(test_hash)
    assert pre["exists"] is False

    # Record via safe fallback
    tx = client.record_provenance_safe(test_hash)
    assert tx["status"] == "SUCCESS"
    assert tx["transaction_hash"].startswith("0x")
    assert tx["block_number"] >= 14
    assert tx["gas_used"] > 0

    # Query again via safe fallback
    post = client.verify_provenance_safe(test_hash)
    assert post["exists"] is True
    assert post["timestamp"] > 0
    assert post["recorder"].startswith("0x")

