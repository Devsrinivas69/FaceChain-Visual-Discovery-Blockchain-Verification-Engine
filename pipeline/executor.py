"""
Core pipeline executor: downloads, evaluates, and ranks search candidates.
This module is the single place that creates CandidateResult objects and
calls apply_evaluation() — ensuring is_match is always set correctly.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from config import FACE_MATCH_THRESHOLD
from extraction.downloader import download_candidate_image, CandidateDownload
from face.detector import FaceDetector
from face.embedding import match_candidate_faces
from search.base import SearchCandidate
from pipeline.models import CandidateResult, CandidateStatus, make_candidate_id

logger = logging.getLogger(__name__)


def evaluate_candidate(
    idx: int,
    search_cand: SearchCandidate,
    detector: FaceDetector,
    query_embedding: np.ndarray,
    threshold: float,
    search_provider: str,
) -> CandidateResult:
    """
    Full evaluation for a single search candidate:
    1. Build CandidateResult object
    2. Download and validate image
    3. Detect faces
    4. Compare embeddings
    5. Set status / is_match via apply_evaluation()

    Returns a fully-populated CandidateResult. Never raises.
    """
    cand_id = make_candidate_id(idx, search_cand.source_domain)
    result = CandidateResult(
        candidate_id=cand_id,
        source_url=search_cand.url,
        source_domain=search_cand.source_domain,
        title=search_cand.title or f"Result from {search_cand.source_domain}",
        image_url=search_cand.image_url,
        thumbnail_url=search_cand.thumbnail_url,
        search_rank=search_cand.search_rank,
        search_provider=search_provider,
    )

    # STEP 1: Download
    try:
        dl: CandidateDownload = download_candidate_image(
            image_url=search_cand.image_url,
            candidate_page_url=search_cand.url,
            fallback_thumbnail_url=search_cand.thumbnail_url,
            prefix=f"{cand_id}",
            raise_on_error=False,
        )

        if not dl.success:
            result.mark_download_failed(dl.error or "Unknown download error")
            return result

        # Populate download fields
        result.download_success = True
        result.local_path = str(dl.local_path) if dl.local_path else None
        result.resolved_url = dl.resolved_url
        result.content_type = dl.content_type
        result.byte_size = dl.byte_size
        result.image_sha256 = dl.image_sha256

    except Exception as exc:
        result.mark_download_failed(str(exc))
        logger.warning(f"[{cand_id}] Download exception: {exc}")
        return result

    # STEP 2: Face detection
    try:
        local_path = Path(result.local_path)
        if not local_path.is_file():
            result.mark_download_failed("Local file missing after download")
            return result

        cand_faces = detector.detect_faces(local_path)
        faces_count = len(cand_faces)

    except Exception as exc:
        result.mark_match_error(f"Face detection failed: {exc}")
        logger.warning(f"[{cand_id}] Face detection error: {exc}")
        return result

    # STEP 3: Embedding comparison
    highest_sim = 0.0
    best_face_idx = -1

    if faces_count > 0:
        try:
            highest_sim, best_face = match_candidate_faces(query_embedding, cand_faces)
            if best_face is not None:
                best_face_idx = cand_faces.index(best_face) if best_face in cand_faces else 0
        except Exception as exc:
            result.mark_match_error(f"Embedding comparison failed: {exc}")
            logger.warning(f"[{cand_id}] Similarity error: {exc}")
            return result

    # STEP 4: Final status assignment (single place where is_match is set)
    result.apply_evaluation(
        faces_count=faces_count,
        face_similarity=highest_sim,
        matched_face_index=best_face_idx,
        threshold=threshold,
    )

    logger.info(
        f"[{cand_id}] {result.source_domain}: "
        f"faces={faces_count}, sim={highest_sim:.3f}, "
        f"status={result.status.value}"
    )
    return result


def rank_candidates(
    candidates: List[CandidateResult],
) -> List[CandidateResult]:
    """
    Sort candidates by face_similarity DESC (primary), search_rank ASC (secondary).
    Face similarity always dominates.
    """
    return sorted(
        candidates,
        key=lambda c: (c.face_similarity, -c.search_rank),
        reverse=True,
    )


def get_matches(
    candidates: List[CandidateResult],
) -> List[CandidateResult]:
    """Return only candidates with status == MATCH, sorted by similarity."""
    return [c for c in candidates if c.is_match and c.status == CandidateStatus.MATCH]


def compute_composite_score(
    face_similarity: float,
    search_rank: int,
    has_accessible_image: bool,
) -> float:
    """
    Transparent composite score for UI display.
    Face similarity is 80% of the score.
    """
    sim_component = face_similarity * 80.0
    rank_component = max(0.0, 10.0 - (search_rank * 0.5))
    media_component = 5.0 if has_accessible_image else 0.0
    return round(sim_component + rank_component + media_component, 2)


# Max parallel workers for concurrent image download + face evaluation.
# Use 6 threads: download is I/O-bound so parallelism gives 4-6x speedup.
_EVAL_MAX_WORKERS = 6
# Hard timeout per candidate evaluation in seconds (download + detect + embed).
_EVAL_CANDIDATE_TIMEOUT_S = 25


def run_candidate_evaluation(
    search_candidates: List[SearchCandidate],
    detector: FaceDetector,
    query_embedding: np.ndarray,
    threshold: float = FACE_MATCH_THRESHOLD,
    search_provider: str = "unknown",
    progress_callback=None,
) -> Tuple[List[CandidateResult], List[CandidateResult]]:
    """
    Evaluate all search candidates end-to-end in parallel.
    Returns (all_results, match_results) both as CandidateResult lists.

    Uses a ThreadPoolExecutor so that image downloads (I/O-bound) run
    concurrently, giving a 4-6x wall-clock speedup over serial evaluation.
    Face detection/embedding (CPU-bound) is fast relative to download latency.
    """
    total = len(search_candidates)
    # index_map keeps futures in submission order so we can restore original rank order
    future_to_idx: dict = {}
    ordered: List[Optional[CandidateResult]] = [None] * total
    completed_count = 0

    with ThreadPoolExecutor(max_workers=min(_EVAL_MAX_WORKERS, max(1, total))) as pool:
        for idx, sc in enumerate(search_candidates, 1):
            future = pool.submit(
                evaluate_candidate,
                idx,
                sc,
                detector,
                query_embedding,
                threshold,
                search_provider,
            )
            future_to_idx[future] = idx - 1  # 0-based position

        for future in as_completed(future_to_idx, timeout=_EVAL_CANDIDATE_TIMEOUT_S * total):
            pos = future_to_idx[future]
            completed_count += 1
            try:
                result = future.result(timeout=_EVAL_CANDIDATE_TIMEOUT_S)
            except FuturesTimeout:
                sc = search_candidates[pos]
                result = CandidateResult(
                    candidate_id=make_candidate_id(pos + 1, sc.source_domain),
                    source_url=sc.url,
                    source_domain=sc.source_domain,
                    title=sc.title or f"Result from {sc.source_domain}",
                    image_url=sc.image_url,
                    thumbnail_url=sc.thumbnail_url,
                    search_rank=sc.search_rank,
                    search_provider=search_provider,
                )
                result.mark_download_failed("Evaluation timed out")
            except Exception as exc:
                sc = search_candidates[pos]
                result = CandidateResult(
                    candidate_id=make_candidate_id(pos + 1, sc.source_domain),
                    source_url=sc.url,
                    source_domain=sc.source_domain,
                    title=sc.title or f"Result from {sc.source_domain}",
                    image_url=sc.image_url,
                    thumbnail_url=sc.thumbnail_url,
                    search_rank=sc.search_rank,
                    search_provider=search_provider,
                )
                result.mark_download_failed(f"Evaluation error: {exc}")
                logger.warning(f"[pos={pos}] Evaluation future exception: {exc}")

            ordered[pos] = result

            if progress_callback:
                progress_callback(completed_count, total, result.source_domain)

    # Filter out any None slots (shouldn't happen but guard defensively)
    all_results = [r for r in ordered if r is not None]
    ranked = rank_candidates(all_results)
    matches = get_matches(ranked)
    return ranked, matches
