#!/bin/bash
set -e

echo "=================================================="
echo " Starting FaceChain Container Services"
echo "=================================================="

# 1. Start Hardhat node in background
echo "[1/3] Starting background Hardhat Ethereum node..."
cd /app/hardhat
npx hardhat node > /app/hardhat.log 2>&1 &
HARDHAT_PID=$!
cd /app

# 2. Wait for Hardhat RPC to be responsive
echo "Waiting for local Ethereum node to become ready on http://127.0.0.1:8545 ..."
READY=0
for i in $(seq 1 30); do
  if curl -s -X POST --data '{"jsonrpc":"2.0","method":"net_version","params":[],"id":1}' -H "Content-Type: application/json" http://127.0.0.1:8545 > /dev/null 2>&1; then
    echo "[OK] Hardhat node is ready!"
    READY=1
    break
  fi
  sleep 1
done

if [ $READY -ne 1 ]; then
  echo "[WARNING] Hardhat node took longer than expected to start. Attempting contract deployment anyway..."
fi

# 3. Deploy ProvenanceRegistry contract
echo "[2/3] Deploying ProvenanceRegistry contract to local network..."
cd /app/hardhat
npx hardhat run scripts/deploy.js --network localhost
cd /app

# 4. Start Streamlit UI
PORT_TO_USE="${PORT:-8501}"
echo "[3/3] Starting FaceChain Streamlit UI on port $PORT_TO_USE..."
exec streamlit run app.py --server.port "$PORT_TO_USE" --server.address 0.0.0.0 --server.headless true
