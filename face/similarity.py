"""Cosine similarity calculation and formatting for ArcFace embeddings."""

import numpy as np
from typing import Union

def compute_cosine_similarity(
    embedding_a: Union[np.ndarray, list],
    embedding_b: Union[np.ndarray, list],
) -> float:
    """
    Computes cosine similarity between two face embedding vectors:
    similarity = (a . b) / (||a|| * ||b||)

    Cosine similarity for 512-d normalized ArcFace embeddings typically ranges from
    -1.0 to 1.0. For face comparison, values below 0.35 indicate distinct faces,
    while values above 0.45-0.50 indicate high visual face concordance.
    """
    a = np.asarray(embedding_a, dtype=np.float32).flatten()
    b = np.asarray(embedding_b, dtype=np.float32).flatten()

    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    sim = float(np.dot(a, b) / (norm_a * norm_b))
    # Clip for floating point precision
    sim = max(-1.0, min(1.0, sim))
    # Standard non-negative visual representation
    return float(max(0.0, sim))

def format_similarity(score: float) -> str:
    """
    Formats the cosine similarity score strictly adhering to project guidelines:
    - Never uses probability terminology ('probability of same person' is forbidden)
    - Expresses strictly as visual face similarity percentage
    """
    percentage = round(score * 100.0, 1)
    return f"Face similarity: {percentage}%"
