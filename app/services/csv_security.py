"""
CSV upload security validation.
Detects malicious content: scripts, code injection, XSS payloads, etc.
"""
import io
import re
import csv as csv_module
from typing import Tuple

# Max file size (bytes) - 10MB
MAX_CSV_SIZE = 10 * 1024 * 1024

# Max cell length - prevents huge single cells
MAX_CELL_LENGTH = 50000

# Max rows to scan for security issues (full scan on smaller files)
MAX_ROWS_TO_SCAN = 5000

# Patterns that indicate malicious or executable content
DANGEROUS_PATTERNS = [
    # Script tags and event handlers
    (r"<script\b", "Script tag detected"),
    (r"javascript\s*:", "JavaScript URI scheme"),
    (r"vbscript\s*:", "VBScript URI scheme"),
    (r"data\s*:\s*text/html", "Data URI with HTML"),
    (r"data\s*:\s*application/x-", "Data URI with executable type"),
    (r"on\w+\s*=\s*[\"']", "Event handler (onclick, onerror, etc.)"),
    (r"on\w+\s*=\s*[^\s>]+", "Event handler without quotes"),
    # Code injection
    (r"<\?php", "PHP code"),
    (r"<%[\s\S]*%>", "ASP/JSP code block"),
    (r"<\s*%\s*", "Server-side script"),
    (r"eval\s*\(", "eval() call"),
    (r"document\.write\s*\(", "document.write"),
    (r"innerHTML\s*=", "innerHTML assignment"),
    (r"document\.cookie", "Cookie access"),
    (r"window\.location\s*=", "Location redirect"),
    (r"document\.domain", "Domain access"),
    # SQL injection indicators (common patterns)
    (r"(\bunion\b.*\bselect\b|\bselect\b.*\bunion\b)", "SQL UNION injection"),
    (r"\bexec\s*\(", "SQL exec"),
    (r"\bexecute\s+immediate\b", "SQL execute immediate"),
    (r";\s*drop\s+table\b", "SQL DROP TABLE"),
    (r";\s*delete\s+from\b", "SQL DELETE"),
    (r"'\s*or\s+'1'\s*=\s*'1", "SQL tautology"),
    (r"1\s*=\s*1\s*--", "SQL comment injection"),
    # Path traversal
    (r"\.\./\.\./", "Path traversal"),
    (r"%2e%2e%2f", "Encoded path traversal"),
    # Shell / command injection (avoid backtick - can appear in product names)
    (r"\|\s*sh\b", "Shell pipe"),
    (r"\|\s*bash\b", "Bash pipe"),
    (r"\$\s*\(\s*[a-zA-Z_]", "Command substitution $(...)"),
]

_COMPILED_PATTERNS = [(re.compile(p, re.I), msg) for p, msg in DANGEROUS_PATTERNS]


def validate_csv_content(text: str, raw_size: int) -> Tuple[bool, str]:
    """
    Validate CSV content for security issues.
    Returns (is_safe, error_message).
    If is_safe is True, error_message is empty.
    """
    if raw_size > MAX_CSV_SIZE:
        return False, f"File too large. Maximum size is {MAX_CSV_SIZE // (1024*1024)} MB."

    lines = text.splitlines()
    if not lines:
        return True, ""

    # Check header + sample of rows
    rows_to_check = min(len(lines), MAX_ROWS_TO_SCAN)
    sample = "\n".join(lines[:rows_to_check])

    for pattern, msg in _COMPILED_PATTERNS:
        if pattern.search(sample):
            return False, f"Security check failed: {msg}. Uploaded files must not contain code or executable content."

    # Check individual cells for length and dangerous content
    try:
        reader = csv_module.reader(io.StringIO(sample))
        for row_idx, row in enumerate(reader):
            for col_idx, cell in enumerate(row):
                if len(cell) > MAX_CELL_LENGTH:
                    return False, f"Cell in row {row_idx + 1} exceeds maximum length of {MAX_CELL_LENGTH} characters."
                for pattern, msg in _COMPILED_PATTERNS:
                    if pattern.search(cell):
                        return False, f"Security check failed: {msg} in row {row_idx + 1}. Uploaded files must not contain code or executable content."
    except Exception:
        pass  # If CSV parsing fails, the main importer will catch it

    return True, ""
