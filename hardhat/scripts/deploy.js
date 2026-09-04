const hre = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  console.log("==================================================");
  console.log("Deploying ProvenanceRegistry to:", hre.network.name);
  console.log("Deployer address:", deployer.address);

  const balance = await hre.ethers.provider.getBalance(deployer.address);
  console.log("Account balance:", hre.ethers.formatEther(balance), "ETH");

  const ProvenanceRegistry = await hre.ethers.getContractFactory("ProvenanceRegistry");
  const registry = await ProvenanceRegistry.deploy();
  await registry.waitForDeployment();

  const contractAddress = await registry.getAddress();
  console.log("✓ ProvenanceRegistry deployed to:", contractAddress);

  // Export ABI and address for the Python web3 client
  const artifactPath = path.join(
    __dirname,
    "../artifacts/contracts/ProvenanceRegistry.sol/ProvenanceRegistry.json"
  );

  let abi = [];
  if (fs.existsSync(artifactPath)) {
    const artifact = JSON.parse(fs.readFileSync(artifactPath, "utf8"));
    abi = artifact.abi;
  }

  const outputDir = path.join(__dirname, "../../blockchain");
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  const exportData = {
    address: contractAddress,
    network: hre.network.name,
    chainId: hre.network.config.chainId || 31337,
    deployedAt: new Date().toISOString(),
    deployer: deployer.address,
    abi: abi,
  };

  const outputPath = path.join(outputDir, "contract_abi.json");
  fs.writeFileSync(outputPath, JSON.stringify(exportData, null, 2));
  console.log("✓ Contract details exported to:", outputPath);
  console.log("==================================================");
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
