"""Tests for cosine similarity and formatting."""

import numpy as np
from face.similarity import compute_cosine_similarity, format_similarity

def test_cosine_similarity_identical_vectors():
    vec = np.random.randn(512).astype(np.float32)
    sim = compute_cosine_similarity(vec, vec)
    assert abs(sim - 1.0) < 1e-5

def test_cosine_similarity_orthogonal_vectors():
    vec_a = np.zeros(512, dtype=np.float32)
    vec_b = np.zeros(512, dtype=np.float32)
    vec_a[0] = 1.0
    vec_b[1] = 1.0
    sim = compute_cosine_similarity(vec_a, vec_b)
    assert abs(sim - 0.0) < 1e-5

def test_cosine_similarity_zero_vector_handling():
    vec_a = np.zeros(512, dtype=np.float32)
    vec_b = np.random.randn(512).astype(np.float32)
    sim = compute_cosine_similarity(vec_a, vec_b)
    assert sim == 0.0

def test_format_similarity_terminology():
    text = format_similarity(0.9123)
    assert text == "Face similarity: 91.2%"
    # Mandatory requirement: Never say probability
    assert "probability" not in text.lower()
