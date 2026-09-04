// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title ProvenanceRegistry
 * @dev Minimal, tamper-evident registry for visual content provenance hashes.
 * Stores only cryptographic SHA-256 digests (bytes32). Never stores raw media,
 * biometric vectors, or personally identifying information.
 */
contract ProvenanceRegistry {
    struct ProvenanceRecord {
        uint256 timestamp;
        address recorder;
        bool exists;
    }

    // Mapping from canonical provenance hash to its on-chain record
    mapping(bytes32 => ProvenanceRecord) private _records;

    // Total number of unique provenance records anchored
    uint256 public totalRecords;

    // Events
    event ProvenanceRecorded(
        bytes32 indexed hash,
        uint256 timestamp,
        address indexed recorder
    );

    // Custom errors
    error RecordAlreadyExists(bytes32 hash, uint256 recordedAt);
    error InvalidHash();

    /**
     * @notice Records a new provenance hash onto the blockchain.
     * @param hash The 32-byte SHA-256 canonical provenance fingerprint.
     * @return success True if the record was successfully committed.
     */
    function record(bytes32 hash) external returns (bool success) {
        if (hash == bytes32(0)) {
            revert InvalidHash();
        }
        if (_records[hash].exists) {
            revert RecordAlreadyExists(hash, _records[hash].timestamp);
        }

        _records[hash] = ProvenanceRecord({
            timestamp: block.timestamp,
            recorder: msg.sender,
            exists: true
        });

        totalRecords += 1;

        emit ProvenanceRecorded(hash, block.timestamp, msg.sender);
        return true;
    }

    /**
     * @notice Verifies if a given provenance hash exists on-chain and returns metadata.
     * @param hash The 32-byte SHA-256 canonical provenance fingerprint.
     * @return exists Whether the hash is anchored.
     * @return timestamp The block timestamp when it was anchored.
     * @return recorder The Ethereum address that submitted the record.
     */
    function verify(bytes32 hash)
        external
        view
        returns (
            bool exists,
            uint256 timestamp,
            address recorder
        )
    {
        ProvenanceRecord memory r = _records[hash];
        return (r.exists, r.timestamp, r.recorder);
    }

    /**
     * @notice Convenience lookup returning the full ProvenanceRecord struct.
     * @param hash The 32-byte SHA-256 canonical provenance fingerprint.
     */
    function getRecord(bytes32 hash)
        external
        view
        returns (ProvenanceRecord memory)
    {
        return _records[hash];
    }
}
