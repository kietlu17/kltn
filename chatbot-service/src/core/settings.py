import hashlib
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", "").strip(), repr=False)
    gemini_model: str = field(default_factory=lambda: os.getenv("CHATBOT_GEMINI_MODEL", "gemini-2.5-flash"))
    embedding_model: str = field(default_factory=lambda: os.getenv("CHATBOT_EMBEDDING_MODEL", "gemini-embedding-001"))
    embedding_dimensions: int = field(default_factory=lambda: int(os.getenv("CHATBOT_EMBEDDING_DIMENSIONS", "768")))
    qdrant_url: str = field(default_factory=lambda: os.getenv("QDRANT_URL", "http://localhost:6333"))
    product_url: str = field(default_factory=lambda: os.getenv("PRODUCT_SERVICE_URL", "http://localhost:3004").rstrip("/"))
    inventory_url: str = field(default_factory=lambda: os.getenv("INVENTORY_SERVICE_URL", "http://localhost:3007").rstrip("/"))
    review_url: str = field(default_factory=lambda: os.getenv("REVIEW_SERVICE_URL", "http://localhost:3008").rstrip("/"))
    data_dir: str = field(default_factory=lambda: os.getenv("CHATBOT_DATA_DIR", "./data"))
    sync_seconds: int = field(default_factory=lambda: int(os.getenv("CHATBOT_SYNC_SECONDS", "300")))
    timeout: float = field(default_factory=lambda: float(os.getenv("CHATBOT_MODEL_TIMEOUT", "120")))
    image_public_base: str = field(default_factory=lambda: os.getenv("PRODUCT_IMAGE_PUBLIC_BASE_URL", "http://localhost:9000/product-images").rstrip("/"))
    image_hosts: tuple = field(default_factory=lambda: tuple(x.strip().lower() for x in os.getenv("CHATBOT_IMAGE_HOSTS", "").split(",") if x.strip()))
    max_images: int = field(default_factory=lambda: int(os.getenv("CHATBOT_MAX_PRODUCT_IMAGES", "5")))
    max_image_bytes: int = 5 * 1024 * 1024
    session_ttl: int = 24 * 3600

    @property
    def collection(self):
        # Different models/prompt versions must never share an embedding space.
        fingerprint = hashlib.sha256(
            f"v3:langchain:gemini:{self.embedding_model}:{self.embedding_dimensions}:retrieval".encode()
        ).hexdigest()[:12]
        return f"catalog_{fingerprint}"
