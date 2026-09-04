"""Blockchain module for Hardhat local interaction and provenance verification."""

from .client import BlockchainClient, BlockchainError
from .verifier import verify_content, run_tamper_demonstration, VerificationResult

__all__ = [
    "BlockchainClient",
    "BlockchainError",
    "verify_content",
    "run_tamper_demonstration",
    "VerificationResult",
]
