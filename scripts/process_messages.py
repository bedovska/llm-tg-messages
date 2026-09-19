"""Classify Telegram messages with the OpenAI Responses API."""

import csv
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any

import fire
from logkittt.core import add_handlers, get_logger
from logkittt.handlers import DefaultConsoleHandler, DefaultFileHandler
from openai import OpenAI
from openai.lib._parsing._responses import type_to_text_format_param
from openai.types.responses import Response
from pydantic import BaseModel
from tqdm import tqdm


logger = get_logger("could_llm_help", __name__)

DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_LOG_FILE = str(
    Path(__file__).resolve().parents[1] / "logs" / "process_messages.log"
)


def load_prompt(prompt_folder: str) -> tuple[str, type[BaseModel], str]:
    """Load the shared prompt and output model from a prompt folder."""
    folder = Path(prompt_folder)
    prompt_path = folder / "shared-prompt.md"
    schema_path = folder / "output_schema.py"

    if not prompt_path.is_file():
        raise FileNotFoundError(f"Shared prompt not found: {prompt_path}")
    if not schema_path.is_file():
        raise FileNotFoundError(f"Output schema not found: {schema_path}")

    instructions = prompt_path.read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        f"prompt_schema_{folder.name}", schema_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load output schema: {schema_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output_model = getattr(module, "MessageAnalysis", None)
    if not isinstance(output_model, type) or not issubclass(
        output_model, BaseModel
    ):
        raise TypeError(
            f"{schema_path} must define a Pydantic MessageAnalysis model"
        )

    return instructions, output_model, folder.name


def read_messages(
    input_file: str,
    id_column: str,
    text_column: str,
) -> list[dict[str, str]]:
    """Read and validate message rows from a CSV file."""
    with Path(input_file).open(
        "r", encoding="utf-8-sig", newline=""
    ) as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames:
            raise ValueError("input_file has no header")
        for column in (id_column, text_column):
            if column not in reader.fieldnames:
                raise ValueError(f"input_file has no {column!r} column")
        return list(reader)


def build_cache_key(
    model: str,
    prompt_version: str,
    instructions: str,
    output_model: type[BaseModel],
) -> str:
    """Build a stable cache key that changes with the prompt or schema."""
    schema = json.dumps(
        output_model.model_json_schema(), sort_keys=True, ensure_ascii=False
    )
    digest = hashlib.sha256(
        f"{instructions}\n{schema}".encode("utf-8")
    ).hexdigest()[:16]
    return f"telegram-portrait:{model}:{prompt_version}:{digest}"


def serialize_usage(response: Response) -> dict[str, int]:
    """Return API token usage with visible and cached-token breakdowns."""
    usage = response.usage
    if usage is None:
        return {}

    input_details = usage.input_tokens_details
    output_details = usage.output_tokens_details
    cached_tokens = (input_details.cached_tokens or 0) if input_details else 0
    cache_write_tokens = (
        getattr(input_details, "cache_write_tokens", 0) or 0
        if input_details
        else 0
    )
    reasoning_tokens = (
        (output_details.reasoning_tokens or 0) if output_details else 0
    )

    return {
        "input_tokens": usage.input_tokens,
        "cached_input_tokens": cached_tokens,
        "cache_write_input_tokens": cache_write_tokens,
        "uncached_input_tokens": (
            usage.input_tokens - cached_tokens - cache_write_tokens
        ),
        "output_tokens": usage.output_tokens,
        "visible_output_tokens": usage.output_tokens - reasoning_tokens,
        "reasoning_output_tokens": reasoning_tokens,
        "total_tokens": usage.total_tokens,
    }


def result_record(
    message_id: str,
    response: Response,
    output_model: type[BaseModel],
    prompt_version: str,
) -> dict[str, Any]:
    """Convert an API response into the project's JSONL record."""
    parsed = output_model.model_validate_json(response.output_text)
    return {
        "message_id": message_id,
        "output": parsed.model_dump(mode="json"),
        "prompt_version": prompt_version,
        "model": response.model,
        "response_id": response.id,
        "usage": serialize_usage(response),
    }


def error_record(
    message_id: str,
    prompt_version: str,
    model: str,
    error: Exception | dict[str, Any],
) -> dict[str, Any]:
    """Build a JSONL record for a failed message."""
    if isinstance(error, Exception):
        error_value: dict[str, Any] = {
            "type": type(error).__name__,
            "message": str(error),
        }
    else:
        error_value = error
    return {
        "message_id": message_id,
        "output": None,
        "prompt_version": prompt_version,
        "model": model,
        "response_id": None,
        "usage": {},
        "error": error_value,
    }


def write_jsonl_line(destination: Any, record: dict[str, Any]) -> None:
    """Write and flush one JSONL record."""
    destination.write(json.dumps(record, ensure_ascii=False) + "\n")
    destination.flush()


class MessageProcessor:
    """CLI commands for synchronous and Batch API processing."""

    def process(
        self,
        input_file: str,
        output_file: str,
        prompt_folder: str,
        id_column: str = "id",
        text_column: str = "text",
        model: str = DEFAULT_MODEL,
        max_output_tokens: int = 4000,
    ) -> None:
        """Process messages synchronously and write results as JSONL.

        Args:
            input_file: Source CSV containing Telegram messages.
            output_file: Destination JSONL path.
            prompt_folder: Folder containing the prompt and output schema.
            id_column: CSV column containing the original message ID.
            text_column: CSV column containing the message text.
            model: OpenAI model ID.
            max_output_tokens: Maximum output tokens per response.
        """
        input_path = Path(input_file)
        output_path = Path(output_file)
        if input_path.resolve() == output_path.resolve():
            raise ValueError("input_file and output_file must differ")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be at least 1")

        instructions, output_model, prompt_version = load_prompt(
            prompt_folder
        )
        rows = read_messages(input_file, id_column, text_column)
        cache_key = build_cache_key(
            model, prompt_version, instructions, output_model
        )
        client = OpenAI()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        succeeded = 0
        failed = 0
        logger.info(
            "Processing %d messages with model=%s prompt=%s",
            len(rows),
            model,
            prompt_version,
        )
        with output_path.open("w", encoding="utf-8") as destination:
            for row in tqdm(rows, desc="Processing messages", unit="message"):
                message_id = row[id_column]
                try:
                    response = client.responses.parse(
                        model=model,
                        instructions=instructions,
                        input=row[text_column],
                        text_format=output_model,
                        reasoning={"effort": "none"},
                        max_output_tokens=max_output_tokens,
                        prompt_cache_key=cache_key,
                        prompt_cache_options={"mode": "implicit", "ttl": "30m"},
                        store=False,
                    )
                    record = result_record(
                        message_id,
                        response,
                        output_model,
                        prompt_version,
                    )
                    succeeded += 1
                except Exception as error:  # Continue long dataset runs.
                    logger.exception("Failed to process message %s", message_id)
                    record = error_record(
                        message_id, prompt_version, model, error
                    )
                    failed += 1
                write_jsonl_line(destination, record)

        logger.info(
            "Finished processing: total=%d, succeeded=%d, failed=%d, output=%s",
            len(rows),
            succeeded,
            failed,
            output_path,
        )

    def submit_batch(
        self,
        input_file: str,
        prompt_folder: str,
        id_column: str = "id",
        text_column: str = "text",
        model: str = DEFAULT_MODEL,
        max_output_tokens: int = 4000,
    ) -> str:
        """Submit all CSV messages through the OpenAI Batch API.

        Args:
            input_file: Source CSV containing Telegram messages.
            prompt_folder: Folder containing the prompt and output schema.
            id_column: CSV column containing the original message ID.
            text_column: CSV column containing the message text.
            model: OpenAI model ID.
            max_output_tokens: Maximum output tokens per response.

        Returns:
            The OpenAI batch ID needed by ``collect_batch``.
        """
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be at least 1")

        instructions, output_model, prompt_version = load_prompt(
            prompt_folder
        )
        rows = read_messages(input_file, id_column, text_column)
        cache_key = build_cache_key(
            model, prompt_version, instructions, output_model
        )
        text_format = type_to_text_format_param(output_model)
        client = OpenAI()

        logger.info(
            "Preparing batch of %d messages with model=%s prompt=%s",
            len(rows),
            model,
            prompt_version,
        )
        with tempfile.NamedTemporaryFile(
            mode="w+", encoding="utf-8", suffix=".jsonl"
        ) as batch_file:
            for index, row in enumerate(
                tqdm(rows, desc="Preparing batch", unit="message")
            ):
                message_id = row[id_column]
                custom_id = f"{index}:{message_id}"
                if len(custom_id) > 64:
                    raise ValueError(
                        f"Batch custom_id exceeds 64 characters: {custom_id!r}"
                    )
                request = {
                    "custom_id": custom_id,
                    "method": "POST",
                    "url": "/v1/responses",
                    "body": {
                        "model": model,
                        "instructions": instructions,
                        "input": row[text_column],
                        "text": {"format": text_format},
                        "reasoning": {"effort": "none"},
                        "max_output_tokens": max_output_tokens,
                        "prompt_cache_key": cache_key,
                        "prompt_cache_options": {
                            "mode": "implicit",
                            "ttl": "30m",
                        },
                        "store": False,
                        "metadata": {
                            "message_id": message_id,
                            "prompt_version": prompt_version,
                        },
                    },
                }
                batch_file.write(json.dumps(request, ensure_ascii=False) + "\n")

            batch_file.flush()
            batch_file.seek(0)
            uploaded = client.files.create(file=batch_file, purpose="batch")

        batch = client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/responses",
            completion_window="24h",
            metadata={"prompt_version": prompt_version, "model": model},
        )
        logger.info(
            "Submitted batch: batch_id=%s, input_file_id=%s, messages=%d",
            batch.id,
            uploaded.id,
            len(rows),
        )
        return batch.id

    def collect_batch(
        self,
        batch_id: str,
        output_file: str,
        prompt_folder: str,
        model: str = DEFAULT_MODEL,
    ) -> None:
        """Download a completed batch and convert it to project JSONL.

        Args:
            batch_id: OpenAI batch ID returned by ``submit_batch``.
            output_file: Destination JSONL path.
            prompt_folder: Folder containing the prompt and output schema.
            model: Fallback model ID for failed requests.
        """
        _, output_model, prompt_version = load_prompt(prompt_folder)
        client = OpenAI()
        batch = client.batches.retrieve(batch_id)
        if batch.status != "completed" or not batch.output_file_id:
            raise RuntimeError(
                f"Batch {batch_id} is {batch.status!r}; it is not ready to collect"
            )

        content = client.files.content(batch.output_file_id).text
        lines = [line for line in content.splitlines() if line.strip()]
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        succeeded = 0
        failed = 0

        logger.info(
            "Collecting %d results from batch_id=%s", len(lines), batch_id
        )
        with output_path.open("w", encoding="utf-8") as destination:
            for line in tqdm(lines, desc="Collecting batch", unit="message"):
                item = json.loads(line)
                custom_id = item.get("custom_id", "")
                message_id = custom_id.split(":", 1)[-1]
                response_data = item.get("response")
                try:
                    if not response_data or response_data.get("status_code") != 200:
                        raise RuntimeError(
                            json.dumps(
                                item.get("error") or response_data,
                                ensure_ascii=False,
                            )
                        )
                    response = Response.model_validate(response_data["body"])
                    message_id = (response.metadata or {}).get(
                        "message_id", message_id
                    )
                    record = result_record(
                        message_id,
                        response,
                        output_model,
                        prompt_version,
                    )
                    succeeded += 1
                except Exception as error:
                    logger.exception(
                        "Failed to collect batch result %s", custom_id
                    )
                    record = error_record(
                        message_id, prompt_version, model, error
                    )
                    failed += 1
                write_jsonl_line(destination, record)

        logger.info(
            "Finished batch collection: total=%d, succeeded=%d, failed=%d, "
            "output=%s",
            len(lines),
            succeeded,
            failed,
            output_path,
        )
        if batch.error_file_id:
            logger.warning(
                "Batch also has an API error file: file_id=%s",
                batch.error_file_id,
            )


if __name__ == "__main__":
    add_handlers(
        logger,
        __file__,
        [DefaultConsoleHandler(), DefaultFileHandler(DEFAULT_LOG_FILE)],
    )
    fire.Fire(MessageProcessor)
