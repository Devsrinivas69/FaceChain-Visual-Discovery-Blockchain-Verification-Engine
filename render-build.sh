#!/usr/bin/env bash
set -e

echo "=== FaceChain Render Build Started ==="

# Upgrade pip
python -m pip install --upgrade pip

# Install Python requirements
pip install -r requirements.txt

# Install Playwright and Chromium browser binary
python -m playwright install --with-deps chromium

# Optional: If node is available on Render Native, install hardhat packages
if command -v npm >/dev/null 2>&1; then
    echo "Installing Hardhat npm dependencies..."
    (cd hardhat && npm install)
fi

echo "=== FaceChain Render Build Complete ==="
