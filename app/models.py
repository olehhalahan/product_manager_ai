from enum import Enum
from typing import Dict, Optional, List
from pydantic import BaseModel, Field


class ProductAction(str, Enum):
    SKIP = "skip"
    GENERATE_NEW = "generate_new"
    IMPROVE_EXISTING = "improve_existing"
    TRANSLATE = "translate"
    MANUAL_REVIEW = "manual_review"


class ProductStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    NEEDS_REVIEW = "needs_review"


class BatchStatus(str, Enum):
    UPLOADED = "uploaded"
    NORMALIZED = "normalized"
    PROCESSING = "processing"
    PARTIALLY_DONE = "partially_done"
    READY_FOR_REVIEW = "ready_for_review"
    EXPORTED = "exported"


class NormalizedProduct(BaseModel):
    id: str
    title: str
    description: str = ""
    category: Optional[str] = None
    brand: Optional[str] = None
    attributes: Dict[str, str] = Field(default_factory=dict)
    language: Optional[str] = None
    image_url: Optional[str] = None
    status_raw: Optional[str] = None
    price: Optional[str] = None
    sale_price: Optional[str] = None
    currency: Optional[str] = None
    color: Optional[str] = None
    size: Optional[str] = None
    material: Optional[str] = None
    weight: Optional[str] = None
    gtin: Optional[str] = None
    mpn: Optional[str] = None
    condition: Optional[str] = None
    gender: Optional[str] = None
    age_group: Optional[str] = None
    url: Optional[str] = None

    original_row: Dict[str, str] = Field(default_factory=dict)


class ProductResult(BaseModel):
    product: NormalizedProduct
    action: ProductAction
    status: ProductStatus
    optimized_title: Optional[str] = None
    optimized_description: Optional[str] = None
    translated_title: Optional[str] = None
    translated_description: Optional[str] = None
    score: int = 0
    notes: Optional[str] = None
    error: Optional[str] = None

    # v1.2: basic cost tracking fields (to be filled by real AI calls)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class Batch(BaseModel):
    id: str
    status: BatchStatus
    products: List[ProductResult]

    # v1.2: aggregate cost / metadata
    client_id: Optional[str] = None
    total_cost_usd: float = 0.0
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


class BatchSummary(BaseModel):
    id: str
    status: BatchStatus
    total: int
    done: int
    failed: int
    skipped: int
    needs_review: int


class ClientConfig(BaseModel):
    """
    Per-client configuration for prompts and behavior.
    In v1.2 this would be stored in the DB and loaded by client_id.
    """

    id: str
    name: str
    default_language: str = "en"
    seo_style: Optional[str] = None
    tone: Optional[str] = None
    forbidden_words: List[str] = Field(default_factory=list)
    title_max_length: int = 70
    description_min_length: int = 120
    use_premium_model_for_difficult_cases: bool = False

