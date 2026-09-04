"""Local face detection, ArcFace embedding, and similarity comparison."""

from .detector import FaceDetector, DetectedFace
from .embedding import extract_embedding_vector, match_candidate_faces
from .similarity import compute_cosine_similarity, format_similarity

__all__ = [
    "FaceDetector",
    "DetectedFace",
    "extract_embedding_vector",
    "match_candidate_faces",
    "compute_cosine_similarity",
    "format_similarity",
]
