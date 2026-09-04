"""Unit tests for pipeline/models.py — CandidateResult invariants."""

import pytest
from pipeline.models import CandidateResult, CandidateStatus


def make_candidate(**kwargs) -> CandidateResult:
    defaults = dict(
        candidate_id="cand_01",
        source_url="https://example.com/pic.jpg",
        source_domain="example.com",
        title="Test Image",
        image_url=None,
        thumbnail_url=None,
        search_rank=1,
        search_provider="test",
    )
    defaults.update(kwargs)
    return CandidateResult(**defaults)


def test_candidate_is_match_always_present_on_discovery():
    c = make_candidate()
    assert hasattr(c, "is_match")
    assert c.is_match is False
    assert "is_match" in c.to_dict()


def test_candidate_download_failed_is_match_false():
    c = make_candidate()
    c.mark_download_failed("HTTP 403")
    assert c.is_match is False
    assert c.status == CandidateStatus.DOWNLOAD_FAILED
    assert "is_match" in c.to_dict()


def test_candidate_invalid_image_is_match_false():
    c = make_candidate()
    c.mark_invalid_image("HTML response returned")
    assert c.is_match is False
    assert c.status == CandidateStatus.INVALID_IMAGE


def test_candidate_no_face_is_match_false():
    c = make_candidate()
    c.download_success = True
    c.apply_evaluation(faces_count=0, face_similarity=0.0, matched_face_index=-1, threshold=0.45)
    assert c.status == CandidateStatus.NO_FACE
    assert c.is_match is False
    assert c.face_similarity == 0.0


def test_candidate_below_threshold_is_match_false():
    c = make_candidate()
    c.download_success = True
    c.apply_evaluation(faces_count=1, face_similarity=0.30, matched_face_index=0, threshold=0.45)
    assert c.status == CandidateStatus.BELOW_THRESHOLD
    assert c.is_match is False
    assert "is_match" in c.to_dict()


def test_candidate_match_is_match_true():
    c = make_candidate()
    c.download_success = True
    c.apply_evaluation(faces_count=1, face_similarity=0.82, matched_face_index=0, threshold=0.45)
    assert c.status == CandidateStatus.MATCH
    assert c.is_match is True
    assert "is_match" in c.to_dict()


def test_candidate_exactly_at_threshold_is_match_true():
    c = make_candidate()
    c.download_success = True
    c.apply_evaluation(faces_count=1, face_similarity=0.45, matched_face_index=0, threshold=0.45)
    assert c.is_match is True
    assert c.status == CandidateStatus.MATCH


def test_candidate_match_error_is_match_false():
    c = make_candidate()
    c.download_success = True
    c.faces_count = 1
    c.mark_match_error("embedding NaN")
    assert c.is_match is False
    assert c.status == CandidateStatus.MATCH_ERROR


def test_candidate_dict_roundtrip_preserves_is_match():
    c = make_candidate()
    c.download_success = True
    c.apply_evaluation(faces_count=2, face_similarity=0.75, matched_face_index=0, threshold=0.45)
    assert c.is_match is True

    d = c.to_dict()
    assert d["is_match"] is True
    assert d["status"] == "MATCH"

    c2 = CandidateResult.from_dict(d)
    assert c2.is_match is True
    assert c2.status == CandidateStatus.MATCH
    assert c2.face_similarity == 0.75


def test_search_result_not_automatically_match():
    """Candidates start as DISCOVERED with is_match=False regardless of search rank."""
    for rank in [1, 2, 3]:
        c = make_candidate(search_rank=rank)
        assert c.is_match is False
        assert c.status == CandidateStatus.DISCOVERED


def test_no_false_match_when_best_below_threshold():
    """The best candidate should not become a match if below threshold."""
    candidates = []
    sims = [0.21, 0.27, 0.31, 0.36]
    for i, sim in enumerate(sims, 1):
        c = make_candidate(candidate_id=f"cand_{i:02d}", search_rank=i)
        c.download_success = True
        c.apply_evaluation(faces_count=1, face_similarity=sim, matched_face_index=0, threshold=0.45)
        candidates.append(c)

    # None should be a match
    from pipeline.executor import get_matches
    matches = get_matches(candidates)
    assert len(matches) == 0, "No candidate should match when all are below threshold"


def test_ranking_by_similarity_not_search_rank():
    """Higher similarity must rank above lower similarity even if search rank is worse."""
    from pipeline.executor import rank_candidates

    low_sim = make_candidate(candidate_id="low", search_rank=1)
    low_sim.download_success = True
    low_sim.apply_evaluation(faces_count=1, face_similarity=0.23, matched_face_index=0, threshold=0.45)

    high_sim = make_candidate(candidate_id="high", search_rank=5)
    high_sim.download_success = True
    high_sim.apply_evaluation(faces_count=1, face_similarity=0.81, matched_face_index=0, threshold=0.45)

    ranked = rank_candidates([low_sim, high_sim])
    assert ranked[0].candidate_id == "high", "Higher similarity must rank first"
