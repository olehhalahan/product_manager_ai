import csv
from typing import TextIO

from ..models import Batch


def generate_result_csv(batch: Batch, buffer: TextIO) -> None:
    fieldnames = [
        "product_id",
        "old_title",
        "new_title",
        "old_description",
        "new_description",
        "translated_description",
        "action",
        "status",
        "notes",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()

    for result in batch.products:
        writer.writerow(
            {
                "product_id": result.product.id,
                "old_title": result.product.title,
                "new_title": result.optimized_title or "",
                "old_description": result.product.description,
                "new_description": result.optimized_description or "",
                "translated_description": result.translated_description or "",
                "action": result.action.value,
                "status": result.status.value,
                "notes": result.notes or result.error or "",
            }
        )

