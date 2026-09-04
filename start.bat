@echo off
title FaceChain - Visual Discovery & Blockchain Verification Engine
echo ================================================================
echo    FaceChain: Visual Discovery & Blockchain Verification Engine
echo    HH Goa 2026 - Task 3 (Local Face + Web Search + Blockchain)
echo ================================================================
echo.

:: Check Node.js
where node >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Node.js is not found in PATH. Please install Node.js 18+ from https://nodejs.org
    pause
    exit /b 1
)

:: Check Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not found in PATH. Please install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)

:: Check if hardhat node_modules exists, install if missing
if not exist "hardhat\node_modules\" (
    echo [Setup] Installing Hardhat dependencies...
    cd hardhat
    call npm install
    cd ..
)

echo [1/3] Starting Hardhat Local Blockchain Node in background...
start "FaceChain Hardhat Node" /min cmd /c "cd hardhat && npx hardhat node"

echo Waiting for Hardhat node to initialize on port 8545...
set /a attempts=0
:wait_node
timeout /t 2 /nobreak >nul
set /a attempts+=1
powershell -Command "try { $tcp = New-Object System.Net.Sockets.TcpClient('127.0.0.1', 8545); $tcp.Close(); exit 0 } catch { exit 1 }" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    if %attempts% GEQ 15 (
        echo [WARNING] Could not confirm node on port 8545 yet. Proceeding with deployment...
    ) else (
        echo   Waiting for node... (attempt %attempts%/15)
        goto wait_node
    )
)
echo [OK] Hardhat local node is running!

echo.
echo [2/3] Deploying ProvenanceRegistry Smart Contract...
cd hardhat
call npx hardhat run scripts/deploy.js --network localhost
cd ..

echo.
echo [3/3] Launching FaceChain Streamlit Application...
echo Application URL: http://localhost:8501
start http://localhost:8501
python -m streamlit run app.py --server.headless true

pause
