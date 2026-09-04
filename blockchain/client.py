"""Web3 client for interacting with the ProvenanceRegistry smart contract."""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from web3 import Web3
from web3.exceptions import ContractLogicError, TransactionNotFound

from config import BLOCKCHAIN_RPC_URL, CONTRACT_ADDRESS, CONTRACT_ABI_PATH, DEFAULT_GAS_LIMIT
from fingerprint.canonical import to_bytes32_hex

logger = logging.getLogger(__name__)

class BlockchainError(Exception):
    """Raised when interaction with the blockchain node fails."""
    pass

class BlockchainClient:
    """Encapsulates Web3 connection, contract interactions, and event verification."""

    def __init__(
        self,
        rpc_url: str = BLOCKCHAIN_RPC_URL,
        contract_address: Optional[str] = None,
        abi_path: Path = CONTRACT_ABI_PATH,
    ):
        self.rpc_url = rpc_url
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        self.abi_path = Path(abi_path)

        # Attempt to auto-load contract info
        loaded_addr, self.abi = self._load_contract_metadata()
        self.contract_address = contract_address or CONTRACT_ADDRESS or loaded_addr

        self.contract = None
        if self.contract_address and self.abi:
            try:
                checksummed = self.w3.to_checksum_address(self.contract_address)
                self.contract = self.w3.eth.contract(address=checksummed, abi=self.abi)
            except Exception as e:
                logger.warning(f"Could not initialize contract at {self.contract_address}: {e}")

    def is_connected(self) -> bool:
        """Returns True if the Hardhat node RPC is reachable."""
        try:
            return self.w3.is_connected()
        except Exception:
            return False

    def get_default_account(self) -> str:
        """Retrieves first test account from local Hardhat node."""
        if not self.is_connected():
            raise BlockchainError(f"Cannot connect to Hardhat node at {self.rpc_url}. Is 'npx hardhat node' running?")
        accounts = self.w3.eth.accounts
        if not accounts:
            raise BlockchainError("No Ethereum accounts found on local node.")
        return accounts[0]

    def record_provenance(self, provenance_hash_hex: str) -> Dict[str, Any]:
        """
        Anchors the 32-byte canonical provenance hash onto the smart contract.
        Waits for transaction confirmation and returns receipt details.
        """
        if not self.is_connected():
            raise BlockchainError(
                f"Local blockchain node is offline ({self.rpc_url}).\n"
                "Please start Hardhat in a separate terminal: 'cd hardhat && npx hardhat node'"
            )

        if not self.contract:
            raise BlockchainError(
                "Contract is not configured or deployed.\n"
                "Please run deploy script: 'cd hardhat && npx hardhat run scripts/deploy.js --network localhost'"
            )

        account = self.get_default_account()
        hash_bytes32 = bytes.fromhex(provenance_hash_hex.replace("0x", ""))

        try:
            logger.info(f"Submitting provenance record for hash {to_bytes32_hex(provenance_hash_hex)}...")
            tx_func = self.contract.functions.record(hash_bytes32)

            # Build transaction
            tx = tx_func.build_transaction({
                "from": account,
                "nonce": self.w3.eth.get_transaction_count(account),
                "gas": DEFAULT_GAS_LIMIT,
            })

            # In Hardhat localhost development, accounts are unlocked
            tx_hash = self.w3.eth.send_transaction(tx)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=15)

            tx_hex = receipt.transactionHash.hex()
            if not tx_hex.startswith("0x"):
                tx_hex = f"0x{tx_hex}"

            return {
                "status": "SUCCESS" if receipt.status == 1 else "FAILED",
                "transaction_hash": tx_hex,
                "block_number": receipt.blockNumber,
                "gas_used": receipt.gasUsed,
                "recorder_address": account,
                "provenance_hash": to_bytes32_hex(provenance_hash_hex),
            }

        except ContractLogicError as cle:
            raise BlockchainError(f"Smart contract execution reverted: {cle}")
        except Exception as exc:
            raise BlockchainError(f"Transaction failed: {exc}")

    def verify_provenance(self, provenance_hash_hex: str) -> Dict[str, Any]:
        """
        Queries the smart contract to verify if the provenance hash is anchored.

        Returns a dict with:
          - queried_hash:  the 0x-prefixed hash we asked about
          - exists:        True if the chain has a record for this hash
          - timestamp:     block.timestamp of when it was anchored (0 if not found)
          - recorder:      Ethereum address that submitted the record (0x0 if not found)
          - chain_id:      current chain ID (proves we're on the right network)
          - latest_block:  current block number (proves a live RPC call was made)
        """
        if not self.is_connected():
            raise BlockchainError(f"Local blockchain node is offline ({self.rpc_url}).")

        if not self.contract:
            raise BlockchainError("Contract is not configured or deployed.")

        queried_hash = to_bytes32_hex(provenance_hash_hex)
        hash_bytes32 = bytes.fromhex(provenance_hash_hex.replace("0x", ""))

        try:
            # Live call to contract.verify() — this is the actual on-chain lookup
            exists, timestamp, recorder = self.contract.functions.verify(hash_bytes32).call()

            # Also fetch live chain metadata to prove this is a real RPC call
            chain_id = self.w3.eth.chain_id
            latest_block = self.w3.eth.block_number

            return {
                "queried_hash": queried_hash,
                "exists": bool(exists),
                "timestamp": int(timestamp),
                "recorder": recorder if exists else "0x" + "0" * 40,
                "chain_id": chain_id,
                "latest_block": latest_block,
                # Legacy key kept for backward compatibility
                "provenance_hash": queried_hash,
            }
        except Exception as exc:
            raise BlockchainError(f"Query verification failed: {exc}")

    def _load_contract_metadata(self) -> Tuple[str, list]:
        """Loads contract address and ABI from disk if exported by deploy.js."""
        if not self.abi_path.is_file():
            return "", []

        try:
            with open(self.abi_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                addr = data.get("address", "")
                abi = data.get("abi", [])
                return addr, abi
        except Exception:
            return "", []
