"""Collect a reproducible random sample from a historical CSV file."""

import csv
import random
from pathlib import Path

import fire


def collect(historic_file: str, n: int, output: str) -> None:
    """Write a random sample of historical records to a CSV file.

    Args:
        historic_file: Path to the source CSV file.
        n: Number of records to collect.
        output: Path to the output CSV file.
    """
    if n <= 0:
        raise ValueError("n must be greater than zero")

    historic_path = Path(historic_file)
    output_path = Path(output)

    if historic_path.resolve() == output_path.resolve():
        raise ValueError("output must be different from historic_file")

    with historic_path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.reader(source)
        try:
            header = next(reader)
        except StopIteration as error:
            raise ValueError("historic_file is empty") from error
        rows = list(reader)

    if n > len(rows):
        raise ValueError(
            f"n ({n}) is greater than the number of records ({len(rows)})"
        )

    selected_rows = random.Random(42).sample(rows, n)

    with output_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination)
        writer.writerow(header)
        writer.writerows(selected_rows)


if __name__ == "__main__":
    fire.Fire(collect)
