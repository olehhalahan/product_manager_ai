"""Pydantic models for AI positioning pipeline (Merchant / feed)."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


class ProductSnapshot(BaseModel):
    """Normalized product input for LLM prompts."""

    current_title: str = ""
    current_description: str = ""
    brand: str = ""
    product_type: str = ""
    color: str = ""
    material: str = ""
    size: str = ""
    condition: str = ""
    optional_attributes: Dict[str, str] = Field(default_factory=dict)


class ProductSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    core_product: str = ""
    primary_use_case: str = ""
    key_attributes: List[str] = Field(default_factory=list)

    @field_validator("core_product", "primary_use_case", mode="before")
    @classmethod
    def _summary_str(cls, v):
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("key_attributes", mode="before")
    @classmethod
    def _key_attrs(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            t = v.strip()
            return [t] if t else []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []


class SearchIntentModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: str = ""
    type: str = "other"
    relevance_score: int = 0
    commercial_score: int = 0
    confidence_score: int = 0
    reason: str = ""

    @field_validator("intent", "reason", mode="before")
    @classmethod
    def _str_fields(cls, v):
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("type", mode="before")
    @classmethod
    def _type_field(cls, v):
        if v is None or str(v).strip() == "":
            return "other"
        return str(v).strip().lower()

    @field_validator("relevance_score", "commercial_score", "confidence_score", mode="before")
    @classmethod
    def _scores(cls, v):
        try:
            if v is None:
                return 0
            n = int(round(float(v)))
            return max(0, min(10, n))
        except (TypeError, ValueError):
            return 0


class IntentExtractionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    product_summary: ProductSummary = Field(default_factory=ProductSummary)
    search_intents: List[SearchIntentModel] = Field(default_factory=list)
    top_recommended_intents: List[str] = Field(default_factory=list)

    @field_validator("search_intents", mode="before")
    @classmethod
    def _coerce_intents(cls, v):
        if v is None:
            return []
        if isinstance(v, dict):
            return [v]
        return v if isinstance(v, list) else []

    @field_validator("top_recommended_intents", mode="before")
    @classmethod
    def _coerce_top(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            t = v.strip()
            return [t] if t else []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []

    @model_validator(mode="after")
    def _drop_empty_intents(self):
        self.search_intents = [x for x in self.search_intents if (x.intent or "").strip()]
        return self


class FinalGenerationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    final_title: str = ""
    final_description: str = ""
    title_rationale: List[str] = Field(default_factory=list)
    intents_used: List[str] = Field(default_factory=list)
    intents_not_used: List[str] = Field(default_factory=list)

    @field_validator("title_rationale", "intents_used", "intents_not_used", mode="before")
    @classmethod
    def _string_lists(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            t = v.strip()
            return [t] if t else []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []

    @field_validator("final_title", "final_description", mode="before")
    @classmethod
    def _text_fields(cls, v):
        if v is None:
            return ""
        return str(v).strip()


def snapshot_from_normalized_product(product) -> ProductSnapshot:
    """Build snapshot from NormalizedProduct (avoid circular import)."""
    return ProductSnapshot(
        current_title=(product.title or "").strip(),
        current_description=(product.description or "").strip(),
        brand=(product.brand or "").strip(),
        product_type=(product.category or "").strip(),
        color=(product.color or "").strip(),
        material=(product.material or "").strip(),
        size=(product.size or "").strip(),
        condition=(product.condition or "").strip(),
        optional_attributes=dict(product.attributes or {}),
    )


def confidence_summary(selected_models: List[SearchIntentModel]) -> str:
    if not selected_models:
        return "No intents selected; fallback path used."
    confs = [m.confidence_score for m in selected_models if m.confidence_score]
    rels = [m.relevance_score for m in selected_models if m.relevance_score]
    parts = []
    if confs:
        parts.append(f"avg confidence {sum(confs) / len(confs):.1f}/10")
    if rels:
        parts.append(f"avg relevance {sum(rels) / len(rels):.1f}/10")
    return "; ".join(parts) if parts else "OK"


def extraction_to_debug_dict(
    extraction: Optional[IntentExtractionResult],
    raw_response: str = "",
) -> Dict[str, Any]:
    if not extraction:
        return {"parse_error": True, "raw_excerpt": (raw_response or "")[:1200]}
    return extraction.model_dump(mode="json")
