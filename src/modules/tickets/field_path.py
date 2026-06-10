import re
import uuid
from dataclasses import dataclass
from typing import List, Optional

from src.core.exceptions import InvalidFieldReport

PRODUCT_FIELD_PATHS = frozenset({"title", "description", "product_images", "category"})

SKU_FIELD_SUFFIXES = {
    "price": "sku_price",
    "name": "sku_name",
    "images": "sku_image",
}

SKU_PATH_PATTERN = re.compile(
    r"^skus/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/(price|name|images)$",
    re.IGNORECASE,
)


@dataclass
class ParsedFieldReport:
    field_path: str
    message: str
    severity: str
    field_name: str
    sku_id: Optional[uuid.UUID]


def parse_field_path(path: str) -> tuple[str, Optional[uuid.UUID]]:
    if path in PRODUCT_FIELD_PATHS:
        return path, None

    match = SKU_PATH_PATTERN.match(path)
    if match:
        sku_id = uuid.UUID(match.group(1))
        field_name = SKU_FIELD_SUFFIXES[match.group(2)]
        return field_name, sku_id

    raise InvalidFieldReport(f"Invalid field_path: {path}")


def validate_field_reports(
    reports: List,
) -> List[ParsedFieldReport]:
    parsed: List[ParsedFieldReport] = []
    for report in reports:
        try:
            field_name, sku_id = parse_field_path(report.field_path)
        except InvalidFieldReport:
            raise
        parsed.append(
            ParsedFieldReport(
                field_path=report.field_path,
                message=report.message,
                severity=report.severity,
                field_name=field_name,
                sku_id=sku_id,
            )
        )
    return parsed
