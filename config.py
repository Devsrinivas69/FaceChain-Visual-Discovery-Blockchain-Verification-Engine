"""Configuration management for FaceChain pipeline."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

# Base project directories
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
INPUT_DIR = DATA_DIR / "input"
CACHE_DIR = DATA_DIR / "cache"
OUTPUT_DIR = DATA_DIR / "output"

# Ensure runtime directories exist
for directory in [DATA_DIR, INPUT_DIR, CACHE_DIR, OUTPUT_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# Face analysis configuration
# Note on threshold: Cosine similarity for 512-d ArcFace embeddings typically ranges from
# ~0.20-0.35 for unrelated faces, and >0.45-0.50 for the same individual across varying poses/lighting.
# 0.45 is a balanced benchmark threshold, fully configurable.
FACE_MATCH_THRESHOLD: float = float(os.getenv("FACE_MATCH_THRESHOLD", "0.45"))
INSIGHTFACE_MODEL: str = os.getenv("INSIGHTFACE_MODEL", "buffalo_sc")
INSIGHTFACE_PROVIDERS: list[str] = ["CPUExecutionProvider"]

# Web Search configuration
SEARCH_PROVIDER: str = os.getenv("SEARCH_PROVIDER", "yandex").lower()  # yandex | bing | google | auto
MAX_SEARCH_CANDIDATES: int = int(os.getenv("MAX_SEARCH_CANDIDATES", "15"))
SEARCH_HEADLESS: bool = os.getenv("SEARCH_HEADLESS", "true").lower() in ("1", "true", "yes")
SEARCH_TIMEOUT_MS: int = int(os.getenv("SEARCH_TIMEOUT_MS", "30000"))

# Media extraction & download limits
DOWNLOAD_TIMEOUT_SECS: int = int(os.getenv("DOWNLOAD_TIMEOUT_SECS", "12"))
MAX_DOWNLOAD_SIZE_BYTES: int = int(os.getenv("MAX_DOWNLOAD_SIZE_BYTES", str(15 * 1024 * 1024)))  # 15 MB limit
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Blockchain configuration
BLOCKCHAIN_RPC_URL: str = os.getenv("BLOCKCHAIN_RPC_URL", "http://127.0.0.1:8545")
CONTRACT_ADDRESS: str = os.getenv("CONTRACT_ADDRESS", "")
DEFAULT_GAS_LIMIT: int = int(os.getenv("DEFAULT_GAS_LIMIT", "300000"))
CONTRACT_ABI_PATH = BASE_DIR / "blockchain" / "contract_abi.json"
