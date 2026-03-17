from typing import Dict, Iterable, List
import csv


def parse_csv_file(buffer) -> List[Dict[str, str]]:
    """
    Parse CSV into a list of row dicts.
    The buffer must be a text-mode file-like object.
    """
    reader = csv.DictReader(buffer)
    rows: List[Dict[str, str]] = []
    for row in reader:
        # Normalize keys to lower-case for easier mapping later.
        normalized_row = {k.lower(): (v or "").strip() for k, v in row.items()}
        rows.append(normalized_row)
    return rows

