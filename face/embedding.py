"""ArcFace embedding utilities and pairwise evaluation."""

import numpy as np
from typing import List, Tuple
from .detector import DetectedFace, FaceDetector
from .similarity import compute_cosine_similarity

def extract_embedding_vector(face: DetectedFace) -> np.ndarray:
    """Returns normalized 512-d ArcFace embedding vector from a DetectedFace."""
    if face.embedding is None:
        raise ValueError("Detected face has no computed embedding vector.")
    return face.embedding

def match_candidate_faces(
    query_embedding: np.ndarray,
    candidate_faces: List[DetectedFace],
) -> Tuple[float, DetectedFace | None]:
    """
    Compares query face embedding to all detected candidate faces.
    Returns (highest_similarity, best_matching_face).
    If candidate has no detected faces, returns (0.0, None).
    """
    if not candidate_faces:
        return 0.0, None

    best_sim = -1.0
    best_face = None

    for face in candidate_faces:
        if face.embedding is not None:
            sim = compute_cosine_similarity(query_embedding, face.embedding)
            if sim > best_sim:
                best_sim = sim
                best_face = face

    return max(0.0, best_sim), best_face
