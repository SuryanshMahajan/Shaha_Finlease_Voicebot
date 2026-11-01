import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date


MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ROWS = 10_000
MAX_RETURNED_ERRORS = 100
REQUIRED_COLUMNS = {"customer_ref", "display_name", "birth_year"}
ALLOWED_COLUMNS = REQUIRED_COLUMNS | {"phone", "preferred_language", "do_not_call"}


class CsvFormatError(ValueError):
    """The CSV cannot be safely interpreted as a customer import."""


@dataclass(frozen=True)
class CustomerImportRow:
    row_number: int
    customer_ref: str
    display_name: str
    birth_year: int
    phone_last4: str | None
    preferred_language: str
    do_not_call: bool


@dataclass
class ParsedCustomerImport:
    total_rows: int
    rows: list[CustomerImportRow]
    duplicate_rows: int
    rejected_rows: int
    errors: list[dict[str, int | str]]
    errors_truncated: bool


def normalize_display_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def normalize_name_for_comparison(value: str) -> str:
    return normalize_display_name(value).casefold()


def _normalize_customer_ref(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().upper()


def _normalize_phone(value: str) -> tuple[str | None, str | None]:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        return None, None
    if not re.fullmatch(r"[0-9+().\-\s]+", normalized):
        return None, "Use digits and standard phone separators only."
    digits = "".join(character for character in normalized if character.isascii() and character.isdigit())
    if not 7 <= len(digits) <= 15:
        return None, "Phone number must contain 7 to 15 digits."
    return digits[-4:], None


def parse_customer_csv(content: bytes) -> ParsedCustomerImport:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvFormatError("CSV must use UTF-8 encoding.") from exc

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        raw_headers = next(reader)
    except StopIteration as exc:
        raise CsvFormatError("CSV is empty; include the required header row.") from exc
    except csv.Error as exc:
        raise CsvFormatError("CSV header is malformed.") from exc

    headers = [header.strip().casefold() for header in raw_headers]
    if not headers or any(not header for header in headers):
        raise CsvFormatError("CSV headers must be non-empty.")
    if len(headers) != len(set(headers)):
        raise CsvFormatError("CSV contains duplicate column headers.")
    missing = sorted(REQUIRED_COLUMNS - set(headers))
    if missing:
        raise CsvFormatError("Missing required columns: " + ", ".join(missing) + ".")
    unexpected = sorted(set(headers) - ALLOWED_COLUMNS)
    if unexpected:
        raise CsvFormatError("Unsupported columns: " + ", ".join(unexpected) + ".")

    rows: list[CustomerImportRow] = []
    duplicate_rows = 0
    rejected_rows = 0
    errors: list[dict[str, int | str]] = []
    total_error_count = 0
    seen_refs: set[str] = set()
    total_rows = 0

    try:
        for row_number, values in enumerate(reader, start=2):
            if not any(value.strip() for value in values):
                continue
            total_rows += 1
            if total_rows > MAX_IMPORT_ROWS:
                raise CsvFormatError(f"CSV may contain at most {MAX_IMPORT_ROWS} data rows.")

            row_errors: list[tuple[str, str]] = []
            if len(values) != len(headers):
                row_errors.append(("_row", "Row must contain the same number of values as the header."))
                fields: dict[str, str] = {}
            else:
                fields = dict(zip(headers, values, strict=True))

            customer_ref = _normalize_customer_ref(fields.get("customer_ref", ""))
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,63}", customer_ref):
                row_errors.append(("customer_ref", "Use 1 to 64 letters, digits, underscores, or hyphens."))

            display_name = normalize_display_name(fields.get("display_name", ""))
            if not display_name:
                row_errors.append(("display_name", "Name is required."))
            elif len(display_name) > 120:
                row_errors.append(("display_name", "Name must be 120 characters or fewer."))
            elif any(unicodedata.category(character) == "Cc" for character in display_name):
                row_errors.append(("display_name", "Name cannot contain control characters."))

            year_text = unicodedata.normalize("NFKC", fields.get("birth_year", "")).strip()
            birth_year = 0
            if not re.fullmatch(r"[0-9]{4}", year_text):
                row_errors.append(("birth_year", "Enter a four-digit birth year."))
            else:
                birth_year = int(year_text)
                if not 1900 <= birth_year <= date.today().year:
                    row_errors.append(("birth_year", "Birth year must be between 1900 and the current year."))

            phone_last4, phone_error = _normalize_phone(fields.get("phone", ""))
            if phone_error:
                row_errors.append(("phone", phone_error))

            preferred_language = unicodedata.normalize("NFKC", fields.get("preferred_language", "en")).strip().casefold()
            if preferred_language not in {"en", "hi"}:
                row_errors.append(("preferred_language", "Choose en or hi."))
            dnc_text = unicodedata.normalize("NFKC", fields.get("do_not_call", "false")).strip().casefold()
            if dnc_text not in {"true", "false", "yes", "no", "1", "0"}:
                row_errors.append(("do_not_call", "Choose true or false."))

            if row_errors:
                rejected_rows += 1
                total_error_count += len(row_errors)
                errors.extend(
                    {"row": row_number, "field": field, "message": message}
                    for field, message in row_errors
                    if len(errors) < MAX_RETURNED_ERRORS
                )
                continue

            if customer_ref in seen_refs:
                duplicate_rows += 1
                continue
            seen_refs.add(customer_ref)
            rows.append(
                CustomerImportRow(
                    row_number=row_number,
                    customer_ref=customer_ref,
                    display_name=display_name,
                    birth_year=birth_year,
                    phone_last4=phone_last4,
                    preferred_language=preferred_language,
                    do_not_call=dnc_text in {"true", "yes", "1"},
                )
            )
    except csv.Error as exc:
        raise CsvFormatError("CSV contains malformed quoting or row data.") from exc

    return ParsedCustomerImport(
        total_rows=total_rows,
        rows=rows,
        duplicate_rows=duplicate_rows,
        rejected_rows=rejected_rows,
        errors=errors,
        errors_truncated=total_error_count > len(errors),
    )
