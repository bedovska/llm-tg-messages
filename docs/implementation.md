# Implementation details
The implementation plan should be updated whenever code changes occur.

## Implementation plan
- [x] Collect a test dataset from historical data.
  It should contain approximately 100 messages that I can use to test and tune LLM results before a full data run.
  Use the `data/december/gemma3-hatespeech-december.csv` file.
  The sampling script preserves every CSV column and uses a fixed random seed so
  repeated runs produce the same dataset:
  `python scripts/collect_test_dataset.py --historic_file=SOURCE.csv --n=100 --output=SAMPLE.csv`

- [x] Pre-filter irrelevant messages with a keyword-based filter.
  `scripts/filter_irrelevant_messages.py` preserves the source columns in the
  accepted CSV and can write rejected rows to a separate CSV with a
  `filter_reason` column. The conservative rules reject empty or very short
  messages, operational air-alert updates, clear advertising, and utility
  outage schedules. Common channel subscription footers are ignored when
  measuring message length, but do not cause rejection by themselves.
  Example:
  `python scripts/filter_irrelevant_messages.py`
  `--input_file=data/test/dataset.csv --output_file=/tmp/relevant.csv`
  `--rejected_file=/tmp/rejected.csv`


- [x] Perform classification and extraction through the OpenAI API.
  - The script will pass Telegram messages through an LLM to extract structured information from each relevant message.
  - Each prompt version is stored in its own `./prompts/<version>/` folder.
    Its `shared-prompt.md` includes the task description, classification rules,
    and label definitions.
    It also defines what information should be extracted from each message to build a social group portrait later.
  - Pass the entire shared prompt through the Python SDK's `instructions=` parameter.
  - Pass the Telegram message separately through the `input=` parameter.
  - Evidence is required for every analyzed subject.
  - The list of allowed subjects is defined by the output schema.
  - I expect to use structured model output. Each prompt version defines its
    output schema in `./prompts/<version>/output_schema.py`.
  - Use GPT-5.6 Luna with no reasoning.
  - I expect to use cached tokens for the shared prompt.
  - There should be an option to pass data through the Batch API for full data processing in the future.
  - Should we preprocess messages (convert them to lowercase, remove certain content, etc.)?
  - If a message is irrelevant, is it possible to avoid spending output tokens on generating the entire structure?

  - I want to track how many tokens were sent as input (the prompt, schema, message itself, and cached tokens) and how many were received as output tokens (visible tokens and reasoning tokens, if used).

  - The output should be saved in JSONL format. It should contain the message
    ID, LLM output, prompt version, and token usage. The message ID is the
    source-qualified `{source}/{id}` value built from the input CSV columns.

  `scripts/process_messages.py` is agnostic of the prompt version. It reads the
  shared prompt and Pydantic schema from any compatible folder passed through
  `--prompt_folder`, so adding or updating a prompt version does not require a
  processing-code change. It sends the prompt as
  `instructions`, sends each unchanged message as `input`, and uses structured
  output with `gpt-5.6-luna` and reasoning effort `none`. Results are written
  incrementally as JSONL, including the source-qualified `{source}/{id}`
  message ID, parsed output, prompt version, response/model identifiers, and
  input, cached, cache-write, visible output, and reasoning token counts.
  Irrelevant messages still produce the schema's minimal
  `{relevant: false, subjects: []}` output. Results generated before the
  source-qualified ID change must be regenerated before visualization.

  Asynchronous processing uses the legacy HTTPX transport for stable TLS
  handling and allows up to 20 requests concurrently:
  `python scripts/process_messages.py process`
  `--input_file=data/test/relevant.csv --output_file=/tmp/results.jsonl`
  `--prompt_folder=prompts/<version>`

  Batch processing is split into submission and collection because OpenAI runs
  a batch asynchronously. Save the batch ID printed by the first command:
  `python scripts/process_messages.py submit_batch`
  `--input_file=data/test/relevant.csv --prompt_folder=prompts/<version>`
  `python scripts/process_messages.py collect_batch --batch_id=BATCH_ID`
  `--output_file=/tmp/results.jsonl --prompt_folder=prompts/<version>`

  All commands show a `tqdm` progress bar. Runtime information and errors are
  logged to both the console and `logs/process_messages.log`.

- [x] Visualize the results.
  - Create a simple web utility that shows results from the JSONL file alongside the original messages for manual validation.
  - It should display a list of all messages on the left. Clicking a message should display its full information on the right.
  - Messages should be filterable by subject.

  `scripts/visualize_results.py` starts a local FastAPI web viewer. It joins the
  original CSV and processing results by the source-qualified `{source}/{id}`
  message ID, preserves the CSV order, and shows relevant, irrelevant, failed,
  and missing results. The left pane can be filtered by any extracted subject;
  the right pane shows the full message, source metadata, extracted fields,
  token usage, and processing metadata.

  `python scripts/visualize_results.py`
  `--input_file=data/test/relevant.csv`
  `--results_file=data/test/results.jsonl`

- [x] Annotate and validate processing results.
  `scripts/annotate_results.py` provides a separate FastAPI interface based on
  the result viewer. It displays the original message and LLM output, accepts
  one feedback item per non-empty textarea line, and lets reviewers mark each
  message as validated. The sidebar preserves CSV order within separate `TBD`
  and `Done` lists, with subject filtering applied to both.

  Review state is stored only in a canonical Markdown file in the relevant
  prompt folder. The folder must contain `shared-prompt.md` and
  `output_schema.py`. On startup, the annotator creates the file if necessary,
  adds missing current messages, preserves records absent from the current
  CSV, and warns about both orphan feedback and result prompt-version
  mismatches. Malformed feedback aborts startup before any rewrite.

  The server rereads the Markdown file before each update, changes only the
  submitted message field, and replaces the file atomically under a write
  lock. The browser saves completed lines on Enter, flushes pending text on
  blur or navigation, saves validation changes immediately, and keeps failed
  writes visible without moving the message.

  `python scripts/annotate_results.py`
  `--input_file=data/test/relevant.csv`
  `--results_file=data/test/results.jsonl`
  `--feedback_file=prompts/v3/feedback.md`

- [x] Count token usage.
  `scripts/count_token_usage.py` reads a processing-results JSONL file and sums
  each token type separately. It prints a human-readable token count without
  per-model details. Records with missing usage do not contribute to the
  totals, and additional future fields ending in `_tokens` are collected
  internally.

  Print the summary:
  `python scripts/count_token_usage.py --input_file=data/test/results.jsonl`

  Or save the same plain-text summary to a file:
  `python scripts/count_token_usage.py --input_file=data/test/results.jsonl`
  `--output_file=/tmp/token_usage.json`

  To calculate cost, pass per-million-token prices in the order regular input,
  cached input, and output. Cached tokens are excluded from the regular input
  count to avoid double charging. Cache-write tokens use the regular input
  price, and reasoning tokens are included in the output count. Costs are
  displayed as exact decimals in the same monetary unit as the prices:
  `python scripts/count_token_usage.py --input_file=data/test/results.jsonl`
  `--token_prices=[0.2,0.02,1.2]`

## Project structure
- Python scripts should be stored under `./scripts`.
- Shared prompts and the required output schema should be stored under `./prompts/`.
- Historical data is available in the `./data/historic/` folder.
  This data can be used for testing during the proof-of-concept stage.
  New data will also be placed in the data folder, probably with a different folder structure.
