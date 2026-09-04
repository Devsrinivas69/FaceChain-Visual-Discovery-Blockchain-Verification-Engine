#!/usr/bin/env bash
set -e

echo "================================================================"
echo "   FaceChain: Visual Discovery & Blockchain Verification Engine"
echo "   HH Goa 2026 - Task 3 (Local Face + Web Search + Blockchain)"
echo "================================================================"
echo ""

# Check prerequisites
command -v node >/dev/null 2>&1 || { echo >&2 "[ERROR] Node.js is required. Install Node.js 18+"; exit 1; }
command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1 || { echo >&2 "[ERROR] Python 3 is required."; exit 1; }

PYTHON_BIN=$(command -v python3 || command -v python)

# Install npm packages in hardhat if missing
if [ ! -d "hardhat/node_modules" ]; then
    echo "[Setup] Installing Hardhat dependencies..."
    (cd hardhat && npm install)
fi

# 1. Start Hardhat node in background
echo "[1/3] Starting Hardhat Local Blockchain Node in background..."
(cd hardhat && npx hardhat node) > hardhat.log 2>&1 &
HARDHAT_PID=$!

cleanup() {
    echo ""
    echo "Stopping background Hardhat node (PID: $HARDHAT_PID)..."
    kill $HARDHAT_PID 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Wait for node to be available on port 8545
echo "Waiting for Hardhat node on port 8545..."
for i in {1..20}; do
    if curl -s -X POST --data '{"jsonrpc":"2.0","method":"net_version","params":[],"id":1}' -H "Content-Type: application/json" http://127.0.0.1:8545 >/dev/null 2>&1; then
        echo "[OK] Hardhat local node connected!"
        break
    fi
    sleep 1
done

# 2. Deploy smart contract
echo ""
echo "[2/3] Deploying ProvenanceRegistry Smart Contract..."
(cd hardhat && npx hardhat run scripts/deploy.js --network localhost)

# 3. Launch Streamlit UI
echo ""
echo "[3/3] Launching FaceChain Streamlit Application..."
echo "Opening http://localhost:8501 ..."
$PYTHON_BIN -m streamlit run app.py --server.port ${PORT:-8501} --server.address 0.0.0.0
