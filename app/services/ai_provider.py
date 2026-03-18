import re
from typing import Dict, List, Optional, Set, Tuple

try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    openai = None

from ..models import NormalizedProduct


_STOP_WORDS: Set[str] = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "as", "be", "was", "are",
    "this", "that", "these", "those", "its", "our", "your", "my", "his",
    "her", "their", "has", "have", "had", "do", "does", "did", "will",
    "can", "may", "not", "all", "any", "each", "very", "just", "also",
    "more", "most", "so", "no", "if", "up", "out", "about", "into",
    "than", "then", "only", "such", "over", "some", "would", "which",
    "been", "when", "what", "who", "how", "make", "like", "use", "new",
    "one", "two", "get", "set",
}

_TYPE_SUFFIXES = [
    "Set", "Kit", "Bundle", "Pack", "Collection", "Edition",
    "Accessory", "Accessories", "Supply", "Supplies",
]


class AIProvider:
    """
    Thin abstraction over the real LLM provider.
    Uses OpenAI when API key is set, otherwise falls back to placeholder.
    """

    def __init__(self):
        self._api_key: str = ""
        self._client = None
        self._prompt_title: str = ""
        self._prompt_description: str = ""

    def set_api_key(self, key: str) -> None:
        self._api_key = key
        if HAS_OPENAI and key:
            self._client = openai.OpenAI(api_key=key)
        else:
            self._client = None

    def set_prompts(self, title_prompt: str, desc_prompt: str) -> None:
        self._prompt_title = title_prompt
        self._prompt_description = desc_prompt

    def _call_openai(self, prompt: str) -> str:
        """Call OpenAI API and return the response text."""
        if not self._client:
            return ""
        try:
            response = self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.7,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return ""

    # ------------------------------------------------------------------ #
    #  Title optimisation
    # ------------------------------------------------------------------ #
    def generate_title(self, product: NormalizedProduct) -> str:
        base = (product.title or "").strip()
        if not base:
            return base

        # Try OpenAI if available
        if self._client and self._prompt_title:
            attrs_str = ", ".join(f"{k}: {v}" for k, v in (product.attributes or {}).items())
            prompt = self._prompt_title.format(
                title=base,
                category=product.category or "",
                brand=product.brand or "",
                attributes=attrs_str,
            )
            result = self._call_openai(prompt)
            if result:
                return self._clean_title(result, max_len=70)

        # Fallback to placeholder algorithm
        base_lower = base.lower()
        base_words = set(re.findall(r"[a-zA-Z]+", base_lower))

        primary_adds: List[str] = []

        if product.material and product.material.lower() not in base_lower:
            primary_adds.append(product.material.strip())

        if product.color and product.color.lower() not in base_lower:
            primary_adds.append(product.color.strip())

        type_hint = self._extract_type_hint(product)
        if type_hint and type_hint.lower() not in base_lower:
            primary_adds.append(type_hint)

        size_val = product.size or product.attributes.get("size", "")
        if size_val and size_val.lower() not in base_lower:
            primary_adds.append(size_val.strip())

        desc_keywords = self._extract_keywords_from_text(
            product.description or "", base_words, limit=4
        )
        attr_keywords = self._extract_keywords_from_attrs(product, base_words)

        fresh_words = desc_keywords + attr_keywords
        for w in fresh_words:
            if w.lower() not in base_lower and len(primary_adds) < 3:
                primary_adds.append(w)

        if not primary_adds:
            suffix = self._infer_product_suffix(product, base_words)
            if suffix:
                primary_adds.append(suffix)

        primary = base
        if primary_adds:
            for pa in primary_adds:
                candidate = f"{primary} {pa}"
                if len(candidate) > 55:
                    break
                primary = candidate

        secondary = self._build_secondary_phrase(product, base_lower, base_words)

        if secondary and len(primary) + 3 + len(secondary) <= 70:
            title = f"{primary} | {secondary}"
        elif secondary:
            remaining = 70 - len(primary) - 3
            if remaining > 8:
                title = f"{primary} | {secondary[:remaining].rsplit(' ', 1)[0]}"
            else:
                title = primary
        else:
            title = primary

        result = self._clean_title(title, max_len=70)

        if result.lower().strip() == base_lower.strip():
            result = self._force_expand(base, product)

        return result

    # ------------------------------------------------------------------ #
    #  Description optimisation
    # ------------------------------------------------------------------ #
    def generate_description(self, product: NormalizedProduct) -> str:
        title = product.title or "this product"

        # Try OpenAI if available
        if self._client and self._prompt_description:
            attrs_str = ", ".join(f"{k}: {v}" for k, v in (product.attributes or {}).items())
            prompt = self._prompt_description.format(
                title=title,
                category=product.category or "",
                brand=product.brand or "",
                attributes=attrs_str,
                description=product.description or "",
            )
            result = self._call_openai(prompt)
            if result:
                return result

        # Fallback to placeholder algorithm
        details = self._collect_natural_details(product)

        paras: List[str] = []

        opening = f"Discover the {title}"
        if product.category:
            leaf = product.category.split(">")[-1].strip()
            opening += f" — a versatile addition to your {leaf.lower()} collection"
        opening += "."
        paras.append(opening)

        if details:
            paras.append(
                "Crafted with care, this product features "
                + self._join_naturally(details)
                + "."
            )

        desc = product.description or ""
        useful = self._extract_useful_sentences(desc)
        if useful:
            paras.append(useful)

        paras.append(
            f"Whether you are upgrading your setup or looking for the perfect gift, "
            f"the {title} delivers quality and style."
        )

        return " ".join(paras)

    # ------------------------------------------------------------------ #
    #  Scoring
    # ------------------------------------------------------------------ #
    def score_optimization(
        self,
        product: NormalizedProduct,
        new_title: Optional[str],
        new_description: Optional[str],
    ) -> int:
        score = 50
        old_title = product.title or ""
        old_desc = product.description or ""

        if new_title and new_title != old_title:
            len_ratio = len(new_title) / max(len(old_title), 1)
            if len_ratio > 1.2:
                score += 8
            if len_ratio > 1.5:
                score += 5
            if "|" in new_title:
                score += 7
            new_words = set(re.findall(r"[a-zA-Z]+", new_title.lower()))
            old_words = set(re.findall(r"[a-zA-Z]+", old_title.lower()))
            added = new_words - old_words - _STOP_WORDS
            score += min(len(added) * 3, 12)
            if len(new_title) >= 40:
                score += 4
        elif not new_title or new_title == old_title:
            score -= 15

        if new_description and new_description != old_desc:
            if len(new_description) > len(old_desc) * 1.3:
                score += 6
            sentences = re.split(r"[.!?]", new_description)
            if len([s for s in sentences if len(s.strip()) > 10]) >= 3:
                score += 5
        elif not new_description or new_description == old_desc:
            score -= 10

        return max(5, min(score, 98))

    # ------------------------------------------------------------------ #
    #  Translation
    # ------------------------------------------------------------------ #
    def translate_text(self, text: str, target_language: str) -> str:
        """Translate text to target language using OpenAI or placeholder."""
        if not text:
            return ""

        lang_names = {
            "en": "English", "de": "German", "sv": "Swedish",
            "fr": "French", "es": "Spanish", "pl": "Polish",
        }
        lang_name = lang_names.get(target_language.lower(), target_language.upper())

        # Try OpenAI if available
        if self._client:
            prompt = f"Translate the following text to {lang_name}. Return only the translation, nothing else.\n\nText: {text}"
            result = self._call_openai(prompt)
            if result:
                return result

        # Fallback placeholder
        return f"[TRANSLATED TO {lang_name.upper()}] {text}"

    # ------------------------------------------------------------------ #
    #  Private helpers — title
    # ------------------------------------------------------------------ #
    def _extract_keywords_from_text(
        self, text: str, exclude: Set[str], limit: int = 4
    ) -> List[str]:
        if not text:
            return []
        words = re.findall(r"[A-Za-z]{3,}", text)
        seen: Set[str] = set()
        result: List[str] = []
        for w in words:
            low = w.lower()
            if low in _STOP_WORDS or low in exclude or low in seen:
                continue
            seen.add(low)
            result.append(w.capitalize())
            if len(result) >= limit:
                break
        return result

    def _extract_keywords_from_attrs(
        self, product: NormalizedProduct, exclude: Set[str]
    ) -> List[str]:
        skip = {
            "price", "sale_price", "cost", "brand", "currency",
            "gtin", "ean", "upc", "mpn", "sku", "id", "url",
            "image_url", "status", "availability",
        }
        result: List[str] = []
        for k, v in (product.attributes or {}).items():
            if k.lower() in skip or not v:
                continue
            for w in re.findall(r"[A-Za-z]{3,}", v):
                if w.lower() not in exclude and w.lower() not in _STOP_WORDS:
                    result.append(w.capitalize())
                    if len(result) >= 3:
                        return result
        return result

    def _extract_type_hint(self, product: NormalizedProduct) -> str:
        if product.category:
            parts = [p.strip() for p in product.category.split(">")]
            leaf = parts[-1]
            if len(leaf) <= 30:
                return leaf
        for key in ("product_type", "type", "item_type"):
            if key in (product.attributes or {}):
                return product.attributes[key].strip()
        return ""

    def _infer_product_suffix(
        self, product: NormalizedProduct, base_words: Set[str]
    ) -> str:
        for s in _TYPE_SUFFIXES:
            if s.lower() not in base_words:
                return s
        return "Premium"

    def _build_secondary_phrase(
        self, product: NormalizedProduct, base_lower: str, base_words: Set[str]
    ) -> str:
        parts: List[str] = []

        if product.category:
            cat_parts = [c.strip() for c in product.category.split(">")]
            for cp in cat_parts:
                if cp.lower() not in base_lower and len(cp) <= 30:
                    parts.append(cp)
                    if len(parts) >= 2:
                        break

        if product.brand and product.brand.lower() not in base_lower:
            parts.append(f"by {product.brand.strip()}")

        desc_kw = self._extract_keywords_from_text(
            product.description or "", base_words, limit=2
        )
        for kw in desc_kw:
            if kw.lower() not in " ".join(parts).lower():
                parts.append(kw)
                if len(parts) >= 3:
                    break

        return " ".join(parts[:4]).strip()

    def _force_expand(self, base: str, product: NormalizedProduct) -> str:
        """Guaranteed to produce a different title even with zero metadata."""
        desc_words = self._extract_keywords_from_text(
            product.description or "", set(), limit=3
        )
        if desc_words:
            raw = f"{base} {' '.join(desc_words)} | {base} Set"
            return self._clean_title(raw, max_len=70)

        if product.brand:
            raw = f"{base} by {product.brand} | Premium {base}"
            return self._clean_title(raw, max_len=70)

        raw = f"{base} Set | Premium {base} Collection"
        return self._clean_title(raw, max_len=70)

    # ------------------------------------------------------------------ #
    #  Private helpers — description
    # ------------------------------------------------------------------ #
    def _collect_natural_details(self, product: NormalizedProduct) -> List[str]:
        details: List[str] = []
        if product.material:
            details.append(f"{product.material.lower()} construction")
        if product.color:
            details.append(f"a {product.color.lower()} finish")
        if product.size:
            details.append(f"{product.size} sizing")
        if product.weight:
            details.append(f"weighing {product.weight}")
        if product.condition and product.condition.lower() != "new":
            details.append(f"{product.condition.lower()} condition")

        skip = {
            "price", "sale_price", "cost", "brand", "currency",
            "gtin", "ean", "upc", "mpn", "sku", "id",
        }
        for k, v in (product.attributes or {}).items():
            if k.lower() in skip or not v:
                continue
            label = k.replace("_", " ").lower()
            details.append(f"{label}: {v}")
        return details

    @staticmethod
    def _join_naturally(items: List[str]) -> str:
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        return ", ".join(items[:-1]) + " and " + items[-1]

    @staticmethod
    def _extract_useful_sentences(desc: str) -> str:
        if not desc or len(desc.strip()) < 20:
            return ""
        sentences = re.split(r"(?<=[.!?])\s+", desc.strip())
        useful = [s for s in sentences if 15 < len(s) < 300]
        if useful:
            return " ".join(useful[:2])
        return ""

    @staticmethod
    def _clean_title(title: str, max_len: int = 70) -> str:
        title = re.sub(r"\s{2,}", " ", title).strip()
        if len(title) > max_len:
            cut = title[:max_len].rsplit(" ", 1)[0]
            return cut
        return title
