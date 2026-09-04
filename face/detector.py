"""Face detection and analysis using InsightFace FaceAnalysis on CPU."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union
import cv2
import numpy as np
import insightface
from insightface.app import FaceAnalysis

from config import INSIGHTFACE_MODEL, INSIGHTFACE_PROVIDERS

logger = logging.getLogger(__name__)

@dataclass
class DetectedFace:
    bbox: tuple[int, int, int, int]
    det_score: float
    embedding: np.ndarray
    area: int
    landmarks: Optional[np.ndarray] = None

class FaceDetector:
    """
    Local face detector and feature extractor using InsightFace.
    Operates strictly locally on CPU without external API calls or biometric cloud uploads.
    """

    def __init__(
        self,
        model_name: str = INSIGHTFACE_MODEL,
        providers: list[str] = INSIGHTFACE_PROVIDERS,
    ):
        self.model_name = model_name
        self.providers = providers
        logger.info(f"Initializing InsightFace FaceAnalysis ({model_name}) on {providers}...")
        
        # Initialize FaceAnalysis app
        self.app = FaceAnalysis(
            name=self.model_name,
            providers=self.providers,
            allowed_modules=["detection", "recognition"],
        )
        # ctx_id < 0 forces CPU execution
        self.app.prepare(ctx_id=-1, det_size=(640, 640))
        logger.info("InsightFace FaceAnalysis prepared successfully on CPU.")

    def load_image(self, image_input: Union[str, Path, bytes, np.ndarray]) -> np.ndarray:
        """Loads and validates an image as a BGR numpy array.

        Uses OpenCV as the primary decoder and falls back to Pillow for formats
        that OpenCV may not handle on all platforms (WebP, AVIF, HEIC, etc.).
        """
        if isinstance(image_input, np.ndarray):
            return image_input

        if isinstance(image_input, (bytes, bytearray)):
            nparr = np.frombuffer(image_input, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is not None:
                return img
            # Pillow fallback for bytes
            try:
                from PIL import Image
                import io
                pil_img = Image.open(io.BytesIO(bytes(image_input))).convert("RGB")
                return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
            except Exception as e:
                raise ValueError(f"Failed to decode image from raw bytes: {e}")

        path_obj = Path(image_input)
        if not path_obj.is_file():
            raise FileNotFoundError(f"Image path not found: {path_obj}")

        # Primary: OpenCV
        img = cv2.imread(str(path_obj))
        if img is not None:
            return img

        # Fallback: Pillow (handles WebP, AVIF, TIFF, PNG16, etc.)
        try:
            from PIL import Image
            pil_img = Image.open(str(path_obj)).convert("RGB")
            img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
            if img is not None:
                return img
        except Exception:
            pass

        raise ValueError(f"Could not decode image (tried OpenCV + Pillow): {path_obj}")

    def detect_faces(self, image_input: Union[str, Path, bytes, np.ndarray]) -> List[DetectedFace]:
        """
        Detects all faces in the provided image and extracts their normalized embeddings.
        Returns a list of DetectedFace objects sorted by face area descending.
        """
        img_bgr = self.load_image(image_input)
        raw_faces = self.app.get(img_bgr)

        if not raw_faces:
            return []

        detected: List[DetectedFace] = []
        for face in raw_faces:
            bbox = face.bbox
            x1 = max(0, int(bbox[0]))
            y1 = max(0, int(bbox[1]))
            x2 = max(0, int(bbox[2]))
            y2 = max(0, int(bbox[3]))
            area = int(max(0, x2 - x1) * max(0, y2 - y1))
            det_score = float(face.det_score) if hasattr(face, "det_score") else 1.0

            # Normalized ArcFace embedding (512-d)
            emb = face.embedding
            if emb is not None:
                norm = np.linalg.norm(emb)
                if norm > 0:
                    emb = emb / norm

            detected.append(
                DetectedFace(
                    bbox=(x1, y1, x2, y2),
                    det_score=det_score,
                    embedding=emb,
                    area=area,
                    landmarks=face.kps if hasattr(face, "kps") else None,
                )
            )

        # Sort largest face first
        detected.sort(key=lambda f: f.area, reverse=True)
        return detected

    def extract_primary_face(self, image_input: Union[str, Path, bytes, np.ndarray]) -> DetectedFace:
        """
        Extracts the primary (most prominent/largest) face from an image.
        Raises ValueError if no face is detected.
        """
        faces = self.detect_faces(image_input)
        if not faces:
            raise ValueError("No face detected in the provided input image.")

        if len(faces) > 1:
            logger.info(f"Multiple faces detected ({len(faces)}). Selecting largest bounding box.")

        return faces[0]
