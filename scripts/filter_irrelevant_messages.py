"""Remove clearly irrelevant Telegram messages from a CSV file."""

import csv
import re
import unicodedata
from collections import Counter
from pathlib import Path

import fire
from logkittt.core import add_handlers, get_logger
from logkittt.handlers import DefaultConsoleHandler


logger = get_logger("could_llm_help", __name__)

WORD_PATTERN = re.compile(r"[^\W\d_]+(?:[\-'’ʼ][^\W\d_]+)*", re.UNICODE)

# Boilerplate is ignored only when measuring message length. Its presence alone
# does not make a news post advertising.
FOOTER_PATTERN = re.compile(
    r"(?:"
    r"підписатися|підписатись|подписаться|"
    r"надіслати новину|прислать контент|"
    r"написати нам|telegram\s*\|\s*facebook"
    r").*$",
    re.IGNORECASE | re.DOTALL,
)

AIR_ALERT_PATTERNS = (
    re.compile(r"\bтривог[аи]\b"),
    re.compile(r"\b(?:(?:в|у)\s+укритт(?:я|і)|в\s+укрыти[ея])\b"),
    re.compile(
        r"\b(?:відбій|отбой|доразвідк\w*|доразведк\w*)\b"
    ),
    re.compile(r"\bпряму(?:є|ють)\s+до\b"),
    re.compile(r"\bтрима(?:є|ють|ти)\s+курс\b"),
    re.compile(r"\bполетіли\s+далі\b"),
    re.compile(r"\b(?:что[- ]?то\s+летает|щось\s+літає)\b"),
    re.compile(
        r"відстежуйте\s+траєкторію.*тип\s+небезпеки"
    ),
    re.compile(
        r"\bпуск\w*\s+ракет\w*\b.*"
        r"\b(?:ту-?95|ту-?160|монітор\w*)\b"
    ),
    re.compile(r"\b(?:ту-?95|ту-?160)\b.*\bпуск\w*\s+ракет\w*\b"),
)

DIRECT_AD_PATTERNS = (
    re.compile(r"#реклама\b"),
    re.compile(
        r"продовження\s+історії\s+вже\s+в\s+\**instagram\b"
    ),
    re.compile(r"\bcosmolot\b"),
)

AD_SIGNAL_PATTERNS = (
    re.compile(r"\bзниж\w*\b"),
    re.compile(r"\bакці(?:я|ї|ю|єю|ями|ях)\b"),
    re.compile(r"\bвигідн\w*\b"),
    re.compile(r"\bтовар\w*\b"),
    re.compile(r"\bпрограм\w*\s+лояльност\w*\b"),
    re.compile(r"\b(?:купи|купуєш|обирай)\w*\b"),
    re.compile(r"\bцін(?:а|и|ою|у|ами|ах)\b"),
    re.compile(r"\bдоставк\w*\b"),
    re.compile(r"\bменеджер\w*\b"),
    re.compile(r"\bнатискай\w*\b"),
)

UTILITY_SCHEDULE_PATTERNS = (
    re.compile(r"\bзміни\s+гпв\b"),
    re.compile(r"\bграфік\w*\s+(?:погодинн\w*\s+)?відключ\w*\b"),
    re.compile(
        r"\bгодини\s+відсутності\s+електропостачання\b.*\bчерг"
    ),
    re.compile(r"\bтриваліст\w*\s+відключ\w*\b.*\bсайт\w*\b"),
)


def normalize_text(text: str) -> str:
    """Normalize text for matching without changing the CSV value."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = normalized.replace("ʼ", "'").replace("’", "'")
    return re.sub(r"\s+", " ", normalized).strip()


def count_content_words(text: str) -> int:
    """Count words after removing common channel footer boilerplate."""
    content = FOOTER_PATTERN.sub("", text)
    return len(WORD_PATTERN.findall(content))


def rejection_reason(text: str, min_words: int = 6) -> str | None:
    """Return a rejection reason for a clearly irrelevant message."""
    normalized = normalize_text(text)
    if not normalized:
        return "empty"

    word_count = count_content_words(normalized)
    if word_count <= 45 and any(
        pattern.search(normalized) for pattern in AIR_ALERT_PATTERNS
    ):
        return "air_alert"

    if any(pattern.search(normalized) for pattern in DIRECT_AD_PATTERNS):
        return "advertising"

    ad_signals = sum(
        bool(pattern.search(normalized)) for pattern in AD_SIGNAL_PATTERNS
    )
    if ad_signals >= 3:
        return "advertising"

    if any(pattern.search(normalized) for pattern in UTILITY_SCHEDULE_PATTERNS):
        return "utility_schedule"

    if word_count < min_words:
        return "too_short"

    return None


def filter_messages(
    input_file: str,
    output_file: str,
    rejected_file: str | None = None,
    text_column: str = "text",
    min_words: int = 6,
) -> None:
    """Filter clearly irrelevant records from a CSV file.

    Args:
        input_file: Source CSV path.
        output_file: Destination for accepted records.
        rejected_file: Optional destination for rejected records and reasons.
        text_column: Column containing the Telegram message text.
        min_words: Minimum content word count required to keep a message.
    """
    if min_words < 1:
        raise ValueError("min_words must be at least 1")

    input_path = Path(input_file)
    output_path = Path(output_file)
    rejected_path = Path(rejected_file) if rejected_file else None

    paths = [input_path.resolve(), output_path.resolve()]
    if rejected_path:
        paths.append(rejected_path.resolve())
    if len(paths) != len(set(paths)):
        raise ValueError("input_file, output_file, and rejected_file must differ")

    with input_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames:
            raise ValueError("input_file has no header")
        if text_column not in reader.fieldnames:
            raise ValueError(f"input_file has no {text_column!r} column")
        if rejected_path and "filter_reason" in reader.fieldnames:
            raise ValueError("input_file already has a 'filter_reason' column")
        rows = list(reader)

    accepted_rows = []
    rejected_rows = []
    reason_counts: Counter[str] = Counter()
    for row in rows:
        reason = rejection_reason(row.get(text_column, ""), min_words=min_words)
        if reason is None:
            accepted_rows.append(row)
            continue
        reason_counts[reason] += 1
        rejected_rows.append({**row, "filter_reason": reason})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=reader.fieldnames)
        writer.writeheader()
        writer.writerows(accepted_rows)

    if rejected_path:
        rejected_path.parent.mkdir(parents=True, exist_ok=True)
        with rejected_path.open("w", encoding="utf-8", newline="") as destination:
            writer = csv.DictWriter(
                destination,
                fieldnames=[*reader.fieldnames, "filter_reason"],
            )
            writer.writeheader()
            writer.writerows(rejected_rows)

    logger.info(
        "Filtered %d messages: kept=%d, rejected=%d, reasons=%s",
        len(rows),
        len(accepted_rows),
        len(rejected_rows),
        dict(reason_counts),
    )


if __name__ == "__main__":
    add_handlers(logger, __file__, [DefaultConsoleHandler()])
    fire.Fire(filter_messages)
