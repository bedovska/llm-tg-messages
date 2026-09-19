"""Summarize token usage from message-processing JSONL results."""

import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import fire


TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "uncached_input_tokens",
    "output_tokens",
    "visible_output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)
PRICE_NAMES = ("input", "cached_input", "output")
TOKEN_LABELS = {
    "input_tokens": "Input",
    "cached_input_tokens": "Cached input",
    "cache_write_input_tokens": "Cache-write input",
    "uncached_input_tokens": "Uncached input",
    "output_tokens": "Output",
    "visible_output_tokens": "Visible output",
    "reasoning_output_tokens": "Reasoning output",
    "total_tokens": "Total",
}
PRICE_LABELS = {
    "input": "Input",
    "cached_input": "Cached input",
    "output": "Output",
    "total": "Total",
}


def empty_summary() -> dict[str, Any]:
    """Create an empty usage summary."""
    return {
        "records": 0,
        "records_with_usage": 0,
        "records_without_usage": 0,
        "token_usage": {field: 0 for field in TOKEN_FIELDS},
    }


def add_usage(
    summary: dict[str, Any], usage: dict[str, Any], line_number: int
) -> None:
    """Add one record's token fields to a summary."""
    token_values = {
        name: value for name, value in usage.items() if name.endswith("_tokens")
    }
    if not token_values:
        summary["records_without_usage"] += 1
        return

    for name, value in token_values.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(
                f"Line {line_number} has invalid usage.{name}: {value!r}"
            )
        summary["token_usage"].setdefault(name, 0)
        summary["token_usage"][name] += value
    summary["records_with_usage"] += 1


def summarize_usage(input_file: str) -> dict[str, Any]:
    """Read a results JSONL file and return total usage."""
    input_path = Path(input_file)
    total = empty_summary()

    with input_path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid JSON on line {line_number}: {error.msg}"
                ) from error
            if not isinstance(record, dict):
                raise ValueError(f"Line {line_number} must contain an object")

            usage = record.get("usage", {})
            if not isinstance(usage, dict):
                raise ValueError(
                    f"Line {line_number} has a non-object usage value"
                )

            total["records"] += 1
            add_usage(total, usage, line_number)

    return total


def parse_token_prices(token_prices: list[float]) -> dict[str, Decimal]:
    """Validate prices and return exact decimals keyed by token category."""
    if not isinstance(token_prices, (list, tuple)) or len(token_prices) != 3:
        raise ValueError(
            "token_prices must contain exactly three values: "
            "[input, cached_input, output]"
        )

    prices = {}
    for name, value in zip(PRICE_NAMES, token_prices):
        if isinstance(value, bool):
            raise ValueError(f"{name} token price must be a non-negative number")
        try:
            price = Decimal(str(value))
        except InvalidOperation as error:
            raise ValueError(
                f"{name} token price must be a non-negative number"
            ) from error
        if not price.is_finite() or price < 0:
            raise ValueError(f"{name} token price must be a non-negative number")
        prices[name] = price
    return prices


def decimal_text(value: Decimal) -> str:
    """Render a decimal without exponent notation or redundant trailing zeros."""
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def price_summary(
    summary: dict[str, Any], prices: dict[str, Decimal]
) -> dict[str, Any]:
    """Calculate cost for one token summary using per-million prices."""
    usage = summary["token_usage"]
    input_tokens = usage["input_tokens"]
    cached_tokens = usage["cached_input_tokens"]
    if cached_tokens > input_tokens:
        raise ValueError("cached_input_tokens cannot exceed input_tokens")

    token_counts = {
        "input": input_tokens - cached_tokens,
        "cached_input": cached_tokens,
        "output": usage["output_tokens"],
    }
    costs = {
        name: Decimal(count) * prices[name] / Decimal(1_000_000)
        for name, count in token_counts.items()
    }
    return {
        "price_per_million_tokens": {
            name: decimal_text(price) for name, price in prices.items()
        },
        "priced_token_counts": token_counts,
        "cost": {
            **{name: decimal_text(cost) for name, cost in costs.items()},
            "total": decimal_text(sum(costs.values(), Decimal(0))),
        },
    }


def add_pricing(
    summary: dict[str, Any], token_prices: list[float]
) -> None:
    """Add pricing to a completed usage summary."""
    prices = parse_token_prices(token_prices)
    summary["pricing"] = price_summary(summary, prices)


def render_summary(summary: dict[str, Any]) -> str:
    """Render token counts and optional pricing for people to read."""
    lines = ["Token usage"]
    usage = summary["token_usage"]
    for name in TOKEN_FIELDS:
        lines.append(f"  {TOKEN_LABELS[name] + ':':<21} {usage[name]:>12,}")

    pricing = summary.get("pricing")
    if pricing:
        lines.extend(["", "Price"])
        for name in (*PRICE_NAMES, "total"):
            lines.append(
                f"  {PRICE_LABELS[name] + ':':<21} "
                f"{pricing['cost'][name]:>12}"
            )
    return "\n".join(lines)


def count_token_usage(
    input_file: str,
    output_file: str | None = None,
    token_prices: list[float] | None = None,
) -> None:
    """Summarize token usage and print or save it as JSON.

    Args:
        input_file: Message-processing results in JSONL format.
        output_file: Optional destination JSON file. Prints to stdout if omitted.
        token_prices: Optional per-million prices for input, cached input, and
            output tokens, in that order.
    """
    input_path = Path(input_file)
    output_path = Path(output_file) if output_file else None
    if output_path and input_path.resolve() == output_path.resolve():
        raise ValueError("input_file and output_file must differ")

    summary = summarize_usage(input_file)
    if token_prices is not None:
        add_pricing(summary, token_prices)

    rendered = render_summary(summary)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
        return
    sys.stdout.write(rendered + "\n")


if __name__ == "__main__":
    fire.Fire(count_token_usage)
