"""Classify Telegram messages with the OpenAI Responses API."""

import asyncio
import csv
import hashlib
import importlib.util
import json
import random
import tempfile
import time
from pathlib import Path
from typing import Any

import fire
from logkittt.core import add_handlers, get_logger
from logkittt.handlers import DefaultConsoleHandler, DefaultFileHandler
from openai import (
    AsyncOpenAI,
    DefaultAioHttpClient,
    OpenAI,
    RateLimitError,
    Timeout,
)
from openai.lib._parsing._responses import type_to_text_format_param
from openai.types.responses import Response
from pydantic import BaseModel

import httpx


logger = get_logger("could_llm_help", __name__)

DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_LOG_FILE = str(
    Path(__file__).resolve().parents[1] / "logs" / "process_messages.log"
)
PROCESS_CONCURRENCY = 5
DEFAULT_TOKENS_PER_MINUTE = 500_000
TOKEN_RATE_UTILIZATION = 0.9
INITIAL_TOKENS_PER_REQUEST = 3_200
MAX_PROCESS_ATTEMPTS = 3


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
    text_column: str,
) -> list[dict[str, str]]:
    """Read and validate message rows from a CSV file."""
    with Path(input_file).open(
        "r", encoding="utf-8-sig", newline=""
    ) as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames:
            raise ValueError("input_file has no header")
        for column in ("id", "source", text_column):
            if column not in reader.fieldnames:
                raise ValueError(f"input_file has no {column!r} column")
        return list(reader)


def message_id(row: dict[str, str]) -> str:
    """Return the source-qualified Telegram message ID."""
    return f"{row['source']}/{row['id']}"


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


def format_duration(seconds: float) -> str:
    """Format a duration as a compact human-readable value."""
    total_seconds = max(0, round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def log_progress(
    label: str,
    completed: int,
    total: int,
    started_at: float,
) -> None:
    """Log completed work, elapsed time, and estimated remaining time."""
    elapsed = time.monotonic() - started_at
    estimated_remaining = (
        elapsed / completed * (total - completed) if completed else 0
    )
    logger.info(
        "%s: %d/%d done; elapsed=%s; estimated remaining=%s",
        label,
        completed,
        total,
        format_duration(elapsed),
        format_duration(estimated_remaining),
    )


def retry_after_seconds(error: Exception) -> float | None:
    """Return the server-requested retry delay for a rate-limit error."""
    if not isinstance(error, RateLimitError) or error.response is None:
        return None

    value = error.response.headers.get("retry-after")
    if value is None:
        return None

    try:
        return max(0.0, float(value))
    except ValueError:
        return None


class TokenRateLimiter:
    """Evenly pace requests under a configured token-per-minute limit."""

    def __init__(self, tokens_per_minute: int) -> None:
        self.effective_tokens_per_minute = max(
            1,
            int(tokens_per_minute * TOKEN_RATE_UTILIZATION),
        )
        self._seconds_per_token = 60 / self.effective_tokens_per_minute
        self._estimated_tokens = INITIAL_TOKENS_PER_REQUEST
        self._next_request_at = 0.0
        self._lock = asyncio.Lock()
        self.rate_limit_events = 0

    async def acquire(self) -> int:
        """Reserve estimated token capacity and wait until it is available."""
        async with self._lock:
            now = time.monotonic()
            request_at = max(now, self._next_request_at)
            reserved_tokens = self._estimated_tokens
            self._next_request_at = request_at + (
                reserved_tokens * self._seconds_per_token
            )

        delay = request_at - now
        if delay > 0:
            await asyncio.sleep(delay)
        return reserved_tokens

    async def reconcile(self, reserved_tokens: int, actual_tokens: int) -> None:
        """Adjust future capacity using the completed request's usage."""
        async with self._lock:
            adjustment = actual_tokens - reserved_tokens
            self._next_request_at = max(
                time.monotonic(),
                self._next_request_at
                + adjustment * self._seconds_per_token,
            )
            self._estimated_tokens = max(
                1,
                round(0.8 * self._estimated_tokens + 0.2 * actual_tokens),
            )

    async def pause(self, delay: float) -> None:
        """Pause all new requests after a rate-limit response."""
        async with self._lock:
            self.rate_limit_events += 1
            self._next_request_at = max(
                self._next_request_at,
                time.monotonic() + delay,
            )


class MessageProcessor:
    """CLI commands for synchronous, asynchronous, and Batch processing."""

    def process_sync(
        self,
        input_file: str,
        output_file: str,
        prompt_folder: str,
        text_column: str = "text",
        model: str = DEFAULT_MODEL,
        max_output_tokens: int = 4000,
    ) -> None:
        """Process messages synchronously and write results as JSONL.

        Args:
            input_file: Source CSV containing Telegram messages.
            output_file: Destination JSONL path.
            prompt_folder: Folder containing the prompt and output schema.
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
        rows = read_messages(input_file, text_column)
        cache_key = build_cache_key(
            model, prompt_version, instructions, output_model
        )
        client = OpenAI(http_client=httpx.Client())
        output_path.parent.mkdir(parents=True, exist_ok=True)

        succeeded = 0
        failed = 0
        logger.info(
            "Processing %d messages synchronously with model=%s prompt=%s",
            len(rows),
            model,
            prompt_version,
        )
        started_at = time.monotonic()
        with output_path.open("w", encoding="utf-8") as destination:
            for completed, row in enumerate(rows, start=1):
                current_message_id = message_id(row)
                try:
                    response = client.responses.parse(
                        model=model,
                        instructions=instructions,
                        input=row[text_column],
                        text_format=output_model,
                        reasoning={"effort": "none"},
                        max_output_tokens=max_output_tokens,
                        prompt_cache_key=cache_key,
                        prompt_cache_options={
                            "mode": "implicit",
                            "ttl": "30m",
                        },
                        store=False,
                    )
                    record = result_record(
                        current_message_id,
                        response,
                        output_model,
                        prompt_version,
                    )
                    succeeded += 1
                except Exception as error:  # Continue long dataset runs.
                    logger.exception(
                        "Failed to process message %s", current_message_id
                    )
                    record = error_record(
                        current_message_id, prompt_version, model, error
                    )
                    failed += 1
                write_jsonl_line(destination, record)
                log_progress(
                    "Processing messages",
                    completed,
                    len(rows),
                    started_at,
                )

        logger.info(
            "Finished synchronous processing: total=%d, succeeded=%d, "
            "failed=%d, output=%s",
            len(rows),
            succeeded,
            failed,
            output_path,
        )

    async def process(
        self,
        input_file: str,
        output_file: str,
        prompt_folder: str,
        text_column: str = "text",
        model: str = DEFAULT_MODEL,
        max_output_tokens: int = 4000,
        concurrency: int = PROCESS_CONCURRENCY,
        tokens_per_minute: int = DEFAULT_TOKENS_PER_MINUTE,
    ) -> None:
        """Process messages asynchronously and write results as JSONL.

        Args:
            input_file: Source CSV containing Telegram messages.
            output_file: Destination JSONL path.
            prompt_folder: Folder containing the prompt and output schema.
            text_column: CSV column containing the message text.
            model: OpenAI model ID.
            max_output_tokens: Maximum output tokens per response.
            concurrency: Maximum number of simultaneous API requests.
            tokens_per_minute: API token-per-minute limit used for pacing.
        """
        input_path = Path(input_file)
        output_path = Path(output_file)
        if input_path.resolve() == output_path.resolve():
            raise ValueError("input_file and output_file must differ")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be at least 1")
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        if tokens_per_minute < 1:
            raise ValueError("tokens_per_minute must be at least 1")

        instructions, output_model, prompt_version = load_prompt(
            prompt_folder
        )
        rows = read_messages(input_file, text_column)
        cache_key = build_cache_key(
            model, prompt_version, instructions, output_model
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        semaphore = asyncio.Semaphore(concurrency)
        rate_limiter = TokenRateLimiter(tokens_per_minute)

        async def process_once(
            row: dict[str, str],
        ) -> tuple[dict[str, Any], bool, Exception | None]:
            current_message_id = message_id(row)
            try:
                async with semaphore:
                    reserved_tokens = await rate_limiter.acquire()
                    response = await client.responses.parse(
                        model=model,
                        instructions=instructions,
                        input=row[text_column],
                        text_format=output_model,
                        reasoning={"effort": "none"},
                        max_output_tokens=max_output_tokens,
                        prompt_cache_key=cache_key,
                        prompt_cache_options={
                            "mode": "implicit",
                            "ttl": "30m",
                        },
                        store=False,
                    )
                    if response.usage is not None:
                        await rate_limiter.reconcile(
                            reserved_tokens,
                            response.usage.total_tokens,
                        )
                return (
                    result_record(
                        current_message_id,
                        response,
                        output_model,
                        prompt_version,
                    ),
                    True,
                    None,
                )
            except Exception as error:  # Continue long dataset runs.
                return (
                    error_record(
                        current_message_id, prompt_version, model, error
                    ),
                    False,
                    error,
                )

        async def process_row(
            row: dict[str, str],
        ) -> tuple[dict[str, Any], bool]:
            for attempt in range(1, MAX_PROCESS_ATTEMPTS + 1):
                record, was_successful, error = await process_once(row)
                if was_successful:
                    return record, True

                error_type = record["error"]["type"]
                current_message_id = message_id(row)
                server_delay = (
                    retry_after_seconds(error)
                    if error is not None
                    else None
                )
                if isinstance(error, RateLimitError):
                    pause_delay = server_delay or 2 ** (attempt - 1)
                    await rate_limiter.pause(pause_delay)

                if attempt < MAX_PROCESS_ATTEMPTS:
                    retry_delay = 2 ** (attempt - 1)
                    if server_delay is not None:
                        retry_delay = max(retry_delay, server_delay)
                    retry_delay += random.uniform(0, 0.25)
                    logger.warning(
                        "Message %s failed with %s on attempt %d/%d; "
                        "retry scheduled",
                        current_message_id,
                        error_type,
                        attempt,
                        MAX_PROCESS_ATTEMPTS,
                    )
                    await asyncio.sleep(retry_delay)
                    continue

                if error is None:
                    raise AssertionError("Failed attempt has no exception")
                logger.logger.error(
                    "Failed to process message %s after %d attempts",
                    current_message_id,
                    MAX_PROCESS_ATTEMPTS,
                    exc_info=(type(error), error, error.__traceback__),
                    extra={"file_only": True},
                )
                logger.warning(
                    "Message %s failed with %s after %d attempts",
                    current_message_id,
                    error_type,
                    MAX_PROCESS_ATTEMPTS,
                )
                return record, False

            raise AssertionError("Processing attempts unexpectedly exhausted")

        succeeded = 0
        failed = 0
        logger.info(
            "Processing %d messages with model=%s prompt=%s "
            "concurrency=%d tokens_per_minute=%d effective_tpm=%d",
            len(rows),
            model,
            prompt_version,
            concurrency,
            tokens_per_minute,
            rate_limiter.effective_tokens_per_minute,
        )
        # async with AsyncOpenAI(max_retries=0) as client:
        # async with AsyncOpenAI(max_retries=0, http_client=httpx.AsyncClient()) as client:
        async with AsyncOpenAI(
            max_retries=0,
            timeout=Timeout(600.0, connect=30.0),
            http_client=DefaultAioHttpClient(),
        ) as client:
            tasks = [asyncio.create_task(process_row(row)) for row in rows]
            started_at = time.monotonic()
            with output_path.open("w", encoding="utf-8") as destination:
                for completed, task in enumerate(
                    asyncio.as_completed(tasks), start=1
                ):
                    record, was_successful = await task
                    write_jsonl_line(destination, record)
                    if was_successful:
                        succeeded += 1
                    else:
                        failed += 1
                    log_progress(
                        "Processing messages",
                        completed,
                        len(rows),
                        started_at,
                    )

        logger.info(
            "Finished processing: total=%d, succeeded=%d, failed=%d, "
            "rate_limit_events=%d, output=%s",
            len(rows),
            succeeded,
            failed,
            rate_limiter.rate_limit_events,
            output_path,
        )

    def submit_batch(
        self,
        input_file: str,
        prompt_folder: str,
        text_column: str = "text",
        model: str = DEFAULT_MODEL,
        max_output_tokens: int = 4000,
    ) -> str:
        """Submit all CSV messages through the OpenAI Batch API.

        Args:
            input_file: Source CSV containing Telegram messages.
            prompt_folder: Folder containing the prompt and output schema.
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
        rows = read_messages(input_file, text_column)
        cache_key = build_cache_key(
            model, prompt_version, instructions, output_model
        )
        text_format = type_to_text_format_param(output_model)
        client = OpenAI(http_client=httpx.Client())

        logger.info(
            "Preparing batch of %d messages with model=%s prompt=%s",
            len(rows),
            model,
            prompt_version,
        )
        with tempfile.NamedTemporaryFile(
            mode="w+", encoding="utf-8", suffix=".jsonl"
        ) as batch_file:
            started_at = time.monotonic()
            for index, row in enumerate(rows):
                current_message_id = message_id(row)
                custom_id = f"{index}:{current_message_id}"
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
                            "message_id": current_message_id,
                            "prompt_version": prompt_version,
                        },
                    },
                }
                batch_file.write(json.dumps(request, ensure_ascii=False) + "\n")
                log_progress(
                    "Preparing batch",
                    index + 1,
                    len(rows),
                    started_at,
                )

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
        started_at = time.monotonic()
        with output_path.open("w", encoding="utf-8") as destination:
            for completed, line in enumerate(lines, start=1):
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
                log_progress(
                    "Collecting batch",
                    completed,
                    len(lines),
                    started_at,
                )

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
    console_handler = DefaultConsoleHandler()
    console_handler.addFilter(
        lambda record: not getattr(record, "file_only", False)
    )
    add_handlers(
        logger,
        __file__,
        [console_handler, DefaultFileHandler(DEFAULT_LOG_FILE)],
    )
    fire.Fire(MessageProcessor)
