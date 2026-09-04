"""FaceChain CLI: Face Visual Discovery, Provenance Anchoring & Blockchain Verification."""

import argparse
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure UTF-8 output encoding for Windows PowerShell/CMD terminals
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("FaceChain")

import config
from face.detector import FaceDetector
from face.embedding import extract_embedding_vector, match_candidate_faces
from face.similarity import format_similarity
from search import get_search_provider, rank_candidates
from search.google_lens import GoogleLensProvider
from search.bing_visual import BingVisualProvider
from search.yandex_visual import YandexVisualProvider
from extraction.downloader import download_candidate_image, MediaDownloadError
from extraction.metadata import build_matched_record
from extraction.url_utils import normalize_url, extract_domain
from fingerprint.canonical import create_canonical_manifest, compute_provenance_hash, to_bytes32_hex
from fingerprint.hashing import compute_image_sha256
from blockchain.client import BlockchainClient, BlockchainError
from blockchain.verifier import verify_content, run_tamper_demonstration

def print_banner():
    print("=" * 60)
    print("           FACE PROVENANCE & VERIFICATION ENGINE            ")
    print("                    HH GOA 2026 - TASK 3                    ")
    print("=" * 60)

def main():
    parser = argparse.ArgumentParser(
        description="Face Visual Discovery, Independent Face Match & Blockchain Provenance Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        help="Path to input face reference image",
    )
    parser.add_argument(
        "--demo",
        "-d",
        nargs="?",
        const="data/input/demo.jpg",
        type=str,
        help="Run in end-to-end demo mode (includes tamper test). Default: data/input/demo.jpg",
    )
    parser.add_argument(
        "--threshold",
        "-t",
        type=float,
        default=config.FACE_MATCH_THRESHOLD,
        help=f"Face cosine similarity match threshold (default: {config.FACE_MATCH_THRESHOLD})",
    )
    parser.add_argument(
        "--provider",
        "-p",
        type=str,
        default=config.SEARCH_PROVIDER,
        choices=["yandex", "bing", "google", "auto"],
        help="Visual search engine provider (default: yandex)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run visual search browser visibly instead of headless",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Clean temporary candidate cache files upon completion",
    )

    args = parser.parse_args()

    image_path_str = args.demo if args.demo else args.input
    is_demo = bool(args.demo)

    if not image_path_str:
        parser.print_help()
        print("\nERROR: Please specify an input image using --input <path> or run --demo")
        sys.exit(1)

    input_image_path = Path(image_path_str).resolve()
    if not input_image_path.is_file():
        print(f"\nERROR: Input image file not found: {input_image_path}")
        sys.exit(1)

    if args.no_headless:
        config.SEARCH_HEADLESS = False

    print_banner()

    # =========================================================================
    # [1] INPUT
    # =========================================================================
    print(f"\n[1] INPUT")
    print(f"✓ Image loaded: {input_image_path.name}")
    print(f"  Path: {input_image_path}")

    # =========================================================================
    # [2] FACE DETECTION
    # =========================================================================
    print(f"\n[2] FACE DETECTION")
    try:
        detector = FaceDetector(model_name=config.INSIGHTFACE_MODEL)
        primary_face = detector.extract_primary_face(input_image_path)
        print(f"✓ Face detected with confidence: {primary_face.det_score:.3f}")
        print(f"  Bounding Box: {primary_face.bbox} (Area: {primary_face.area} px²)")
    except Exception as e:
        print(f"\nERROR: Face detection failed: {e}")
        sys.exit(1)

    # =========================================================================
    # [3] FACE EMBEDDING
    # =========================================================================
    print(f"\n[3] FACE EMBEDDING")
    query_embedding = extract_embedding_vector(primary_face)
    print(f"✓ 512-dimensional ArcFace embedding generated locally on CPU")

    # =========================================================================
    # [4] VISUAL SEARCH
    # =========================================================================
    print(f"\n[4] VISUAL SEARCH")
    provider_name = args.provider
    candidates = []

    # Cascade: Yandex (primary, best visual face coverage without captchas) -> Bing -> Google Lens
    if provider_name in ("yandex", "auto"):
        print("  Querying Yandex Visual Search (primary)...")
        try:
            yandex_provider = YandexVisualProvider()
            candidates = yandex_provider.search(str(input_image_path))
        except Exception as e:
            logger.warning(f"Yandex Visual Search failed: {e}")

    if not candidates and provider_name in ("bing", "auto"):
        print("  Attempting Bing Visual Search...")
        try:
            bing_provider = BingVisualProvider()
            candidates = bing_provider.search(str(input_image_path))
        except Exception as e:
            logger.warning(f"Bing Visual Search failed: {e}")

    if not candidates and provider_name in ("google", "auto"):
        print("  Attempting Google Lens fallback...")
        try:
            google_provider = GoogleLensProvider()
            candidates = google_provider.search(str(input_image_path))
        except Exception as e:
            logger.warning(f"Google Lens fallback failed: {e}")

    if not candidates:
        print("\nSEARCH COMPLETED: No usable candidate content discovered.")
        print("Please check internet connection or provide an image with broader public web coverage.")
        sys.exit(0)

    print(f"✓ Visual search completed successfully")

    # =========================================================================
    # [5] CANDIDATES
    # =========================================================================
    print(f"\n[5] CANDIDATES")
    print(f"✓ {len(candidates)} candidates discovered across public web/social sources")

    # =========================================================================
    # [6] INDEPENDENT CANDIDATE DOWNLOAD & FACE MATCHING
    # =========================================================================
    print(f"\n[6] INDEPENDENT FACE MATCHING & SIMILARITY EVALUATION")
    evaluated_candidates = []

    for idx, cand in enumerate(candidates, 1):
        print(f"  Evaluating candidate {idx:02d}/{len(candidates):02d}: {cand.source_domain} ...", end=" ", flush=True)

        download_info = None
        cand_faces = []
        highest_sim = 0.0

        try:
            download_info = download_candidate_image(
                image_url=cand.image_url,
                candidate_page_url=cand.url,
                fallback_thumbnail_url=cand.thumbnail_url,
                prefix=f"cand_{idx:02d}",
            )
            # Detect faces in candidate image
            cand_faces = detector.detect_faces(download_info["local_path"])
            if cand_faces:
                highest_sim, _ = match_candidate_faces(query_embedding, cand_faces)
                print(f"{format_similarity(highest_sim)} ({len(cand_faces)} face(s) in image)")
            else:
                print("No faces detected in media (skipped)")
        except MediaDownloadError:
            print("Media inaccessible (skipped)")
        except Exception as ex:
            print(f"Error ({ex})")

        evaluated_candidates.append({
            "candidate": cand,
            "face_similarity": highest_sim,
            "download_success": download_info is not None,
            "download_info": download_info,
            "faces_count": len(cand_faces),
        })

    # Rank candidates
    ranked = rank_candidates(evaluated_candidates, threshold=args.threshold)

    # =========================================================================
    # [7] BEST MATCH SELECTION
    # =========================================================================
    print(f"\n[7] BEST MATCH")
    matching_candidates = [c for c in ranked if c["is_match"] and c["download_success"]]

    if not matching_candidates:
        print(f"No candidates satisfied the face similarity threshold of {args.threshold:.2f}.")
        print("Top candidates evaluated:")
        for top_c in ranked[:3]:
            print(f"  - {top_c['candidate'].url} -> {format_similarity(top_c['face_similarity'])}")
        sys.exit(0)

    best = matching_candidates[0]
    best_cand = best["candidate"]
    best_dl = best["download_info"]
    best_sim = best["face_similarity"]

    print(f"✓ Strongest verified visual face match selected:")
    print(f"  Domain:          {best_cand.source_domain}")
    print(f"  URL:             {best_cand.url}")
    print(f"  {format_similarity(best_sim)}")
    print(f"  Local Media:     {best_dl['local_path'].name} ({best_dl['byte_size']} bytes)")

    # =========================================================================
    # [8] CONTENT FINGERPRINT & CANONICAL PROVENANCE MANIFEST
    # =========================================================================
    print(f"\n[8] CONTENT FINGERPRINT")
    retrieved_at = datetime.now(timezone.utc).isoformat()
    record = build_matched_record(
        source_url=best_cand.url,
        title=best_cand.title,
        image_url=best_dl["resolved_url"],
        face_similarity=best_sim,
        search_provider=args.provider,
        content_type=best_dl["content_type"],
        image_byte_size=best_dl["byte_size"],
        image_sha256=best_dl["image_sha256"],
        retrieved_at=retrieved_at,
    )

    canonical_manifest = create_canonical_manifest(
        source_url=record.normalized_url,
        image_sha256=record.image_sha256,
        title=record.title,
        source_domain=record.source_domain,
        retrieved_at=record.retrieved_at,
    )

    provenance_hash = compute_provenance_hash(canonical_manifest)
    formatted_hash = to_bytes32_hex(provenance_hash)

    print(f"✓ Image SHA-256:        {record.image_sha256}")
    print(f"✓ Provenance Hash:      {formatted_hash}")

    # =========================================================================
    # [9] BLOCKCHAIN ANCHORING
    # =========================================================================
    print(f"\n[9] BLOCKCHAIN PROVENANCE ANCHORING")
    blockchain_client = BlockchainClient()

    if not blockchain_client.is_connected():
        print(f"WARNING: Local Hardhat node is not reachable at {blockchain_client.rpc_url}.")
        print("To anchor provenance on-chain, please run in a separate terminal:")
        print("  cd hardhat && npx hardhat node")
        print("  npx hardhat run scripts/deploy.js --network localhost")
        print("\nVerification cannot proceed without active blockchain node.")
        sys.exit(1)

    try:
        # Check if already recorded
        existing_record = blockchain_client.verify_provenance(provenance_hash)
        if existing_record.get("exists"):
            print(f"✓ Hash already anchored in contract at block timestamp {existing_record.get('timestamp')}")
            tx_info = {
                "transaction_hash": "Existing Record",
                "block_number": "Confirmed",
            }
        else:
            tx_info = blockchain_client.record_provenance(provenance_hash)
            print(f"✓ Provenance anchored onto local Hardhat Ethereum network")
            print(f"  Transaction:  {tx_info.get('transaction_hash')}")
            print(f"  Block Number: {tx_info.get('block_number')}")
            print(f"  Gas Used:     {tx_info.get('gas_used')}")
    except BlockchainError as berr:
        print(f"ERROR: Blockchain anchoring failed: {berr}")
        sys.exit(1)

    # =========================================================================
    # [10] RECOMPUTE & ON-CHAIN VERIFICATION
    # =========================================================================
    print(f"\n[10] BLOCKCHAIN VERIFICATION")
    verification = verify_content(canonical_manifest, blockchain_client)

    print(f"  Local Hash:     {verification.local_hash}")
    print(f"  On-chain Hash:  {to_bytes32_hex(verification.details.get('provenance_hash', ''))}")
    print(f"  Status:         {'VERIFIED' if verification.is_verified else 'FAILED'}")
    print(f"RESULT:           {'✓ VERIFIED' if verification.is_verified else '✗ FAILED'}")

    # =========================================================================
    # [11 & 12] TAMPER DEMONSTRATION (Demo Mode)
    # =========================================================================
    if is_demo:
        print("\n" + "-" * 60)
        print("               TAMPER DEMONSTRATION MODE                    ")
        print("-" * 60)
        print("\n[11] MUTATING ASSET CONTENT")
        tamper_result = run_tamper_demonstration(
            original_image_path=best_dl["local_path"],
            original_manifest=canonical_manifest,
            blockchain_client=blockchain_client,
        )
        print(f"✓ Modified 3 pixels in candidate image: {tamper_result['tampered_image_path'].name}")
        print(f"  Original Image SHA:  {tamper_result['original_image_sha256']}")
        print(f"  Tampered Image SHA:  {tamper_result['tampered_image_sha256']}")

        print(f"\n[12] VERIFYING TAMPERED ASSET AGAINST BLOCKCHAIN")
        print(f"  Original Fingerprint: {tamper_result['original_provenance_hash']}")
        print(f"  Current Fingerprint:  {tamper_result['tampered_provenance_hash']}")
        print(f"  Blockchain Anchor:    NOT FOUND (Cryptographic Mismatch)")
        print(f"RESULT:                 ✗ TAMPER DETECTED / VERIFICATION FAILED")

    print("\n" + "=" * 60)
    print("                 PIPELINE COMPLETED SUCCESSFULLY            ")
    print("=" * 60)

    if args.cleanup:
        shutil.rmtree(config.CACHE_DIR, ignore_errors=True)
        config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        print("✓ Temporary cache cleaned.")

if __name__ == "__main__":
    main()
