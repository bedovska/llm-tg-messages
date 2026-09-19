"""Show Telegram messages and their LLM results in a local web viewer."""

import csv
import json
from pathlib import Path
from typing import Any

import fire
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from logkittt.core import add_handlers, get_logger
from logkittt.handlers import DefaultConsoleHandler, DefaultFileHandler


logger = get_logger("could_llm_help", __name__)

DEFAULT_LOG_FILE = str(
    Path(__file__).resolve().parents[1] / "logs" / "visualize_results.log"
)


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Telegram analysis results</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, sans-serif;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --border: #d9dee5;
      --muted: #657182;
      --text: #18212f;
      --accent: #2563eb;
      --selected: #eef4ff;
      --relevant: #18794e;
      --irrelevant: #667085;
      --error: #b42318;
      --missing: #b54708;
    }

    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); }
    button, select { font: inherit; }
    header {
      padding: 18px 24px;
      background: var(--panel);
      border-bottom: 1px solid var(--border);
    }
    h1 { margin: 0 0 4px; font-size: 22px; }
    h2 { margin: 0 0 14px; font-size: 18px; }
    h3 { margin: 18px 0 10px; font-size: 15px; }
    p { line-height: 1.55; }
    .summary { color: var(--muted); font-size: 14px; }
    .warnings {
      margin-top: 10px;
      padding: 9px 12px;
      color: #7a2e0e;
      background: #fff4e8;
      border: 1px solid #f4c790;
      border-radius: 7px;
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(290px, 370px) minmax(0, 1fr);
      height: calc(100vh - 85px);
    }
    .sidebar {
      display: flex;
      flex-direction: column;
      min-height: 0;
      background: var(--panel);
      border-right: 1px solid var(--border);
    }
    .controls { padding: 14px; border-bottom: 1px solid var(--border); }
    label { display: block; margin-bottom: 6px; color: var(--muted); font-size: 13px; }
    select {
      width: 100%;
      padding: 9px 10px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: #fff;
    }
    .visible-count { margin-top: 8px; color: var(--muted); font-size: 12px; }
    .message-list { overflow-y: auto; }
    .message-item {
      display: block;
      width: 100%;
      padding: 13px 14px;
      border: 0;
      border-bottom: 1px solid var(--border);
      background: transparent;
      color: inherit;
      text-align: left;
      cursor: pointer;
    }
    .message-item:hover { background: #f8fafc; }
    .message-item.selected { background: var(--selected); box-shadow: inset 3px 0 var(--accent); }
    .item-top { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
    .message-id { font-weight: 650; font-size: 13px; }
    .excerpt {
      display: -webkit-box;
      margin: 8px 0;
      overflow: hidden;
      color: #344054;
      font-size: 13px;
      line-height: 1.4;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 3;
    }
    .item-meta { color: var(--muted); font-size: 12px; }
    .badge, .chip {
      display: inline-block;
      padding: 2px 7px;
      border-radius: 999px;
      background: #edf1f5;
      font-size: 11px;
      line-height: 1.6;
    }
    .badge.relevant { color: var(--relevant); background: #e9f7f0; }
    .badge.irrelevant { color: var(--irrelevant); }
    .badge.error { color: var(--error); background: #fff0ee; }
    .badge.missing { color: var(--missing); background: #fff4e8; }
    .detail { min-width: 0; overflow-y: auto; padding: 24px clamp(18px, 4vw, 52px) 60px; }
    .detail-inner { max-width: 1000px; margin: 0 auto; }
    .message-text {
      margin: 0;
      padding: 16px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      line-height: 1.55;
    }
    .section {
      margin-top: 18px;
      padding: 16px;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
    }
    .subject-card { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border); }
    .subject-card:first-of-type { margin-top: 0; padding-top: 0; border-top: 0; }
    .subject-title { margin: 0 0 9px; color: var(--accent); font-size: 15px; }
    dl { margin: 0; }
    .field {
      display: grid;
      grid-template-columns: minmax(140px, 220px) minmax(0, 1fr);
      gap: 12px;
      padding: 7px 0;
      border-bottom: 1px solid #eef1f4;
    }
    .field:last-child { border-bottom: 0; }
    dt { color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
    dd { margin: 0; font-size: 13px; white-space: pre-wrap; overflow-wrap: anywhere; }
    .chips { display: flex; flex-wrap: wrap; gap: 5px; }
    .empty { color: var(--muted); font-style: italic; }
    .error-box { color: var(--error); }

    @media (max-width: 760px) {
      .layout { grid-template-columns: 1fr; height: auto; }
      .sidebar { height: 42vh; border-right: 0; border-bottom: 1px solid var(--border); }
      .detail { overflow: visible; padding: 20px 14px 40px; }
      .field { grid-template-columns: 1fr; gap: 3px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Telegram analysis results</h1>
    <div id="summary" class="summary"></div>
    <div id="warnings" class="warnings" hidden></div>
  </header>
  <main class="layout">
    <aside class="sidebar">
      <div class="controls">
        <label for="subject-filter">Filter by subject</label>
        <select id="subject-filter"></select>
        <div id="visible-count" class="visible-count"></div>
      </div>
      <div id="message-list" class="message-list"></div>
    </aside>
    <section id="detail" class="detail"></section>
  </main>

  <script>
    const viewerData = __VIEWER_DATA__;
    const state = { subject: "", selectedId: null };
    const listElement = document.getElementById("message-list");
    const detailElement = document.getElementById("detail");
    const filterElement = document.getElementById("subject-filter");

    function makeElement(tag, className, text) {
      const element = document.createElement(tag);
      if (className) element.className = className;
      if (text !== undefined && text !== null) element.textContent = String(text);
      return element;
    }

    function displayValue(value) {
      if (value === null || value === undefined || value === "") return "—";
      if (typeof value === "boolean") return value ? "Yes" : "No";
      if (typeof value === "object") return JSON.stringify(value, null, 2);
      return String(value);
    }

    function appendField(list, name, value) {
      const row = makeElement("div", "field");
      row.append(makeElement("dt", "", name));
      const description = makeElement("dd");
      if (Array.isArray(value) && value.length) {
        const chips = makeElement("div", "chips");
        value.forEach(item => chips.append(makeElement("span", "chip", displayValue(item))));
        description.append(chips);
      } else {
        description.textContent = displayValue(value);
      }
      row.append(description);
      list.append(row);
    }

    function appendDataSection(parent, title, values, excludedKeys = []) {
      const section = makeElement("section", "section");
      section.append(makeElement("h2", "", title));
      const list = makeElement("dl");
      Object.entries(values || {}).forEach(([name, value]) => {
        if (!excludedKeys.includes(name)) appendField(list, name, value);
      });
      if (!list.children.length) list.append(makeElement("div", "empty", "No data"));
      section.append(list);
      parent.append(section);
    }

    function filteredMessages() {
      if (!state.subject) return viewerData.messages;
      return viewerData.messages.filter(message => message.subjects.includes(state.subject));
    }

    function renderList() {
      const messages = filteredMessages();
      document.getElementById("visible-count").textContent =
        `${messages.length} of ${viewerData.messages.length} messages`;

      if (!messages.some(message => message.message_id === state.selectedId)) {
        state.selectedId = messages.length ? messages[0].message_id : null;
      }

      listElement.replaceChildren();
      if (!messages.length) {
        listElement.append(makeElement("p", "empty", "No messages match this subject."));
        renderDetail();
        return;
      }

      messages.forEach(message => {
        const button = makeElement(
          "button",
          `message-item${message.message_id === state.selectedId ? " selected" : ""}`
        );
        button.type = "button";
        const top = makeElement("div", "item-top");
        top.append(makeElement("span", "message-id", `#${message.message_id}`));
        top.append(makeElement("span", `badge ${message.status}`, message.status));
        button.append(top);
        button.append(makeElement("div", "excerpt", message.text || "(empty message)"));
        const meta = [message.original.source, message.original.date].filter(Boolean).join(" · ");
        if (meta) button.append(makeElement("div", "item-meta", meta));
        button.addEventListener("click", () => {
          state.selectedId = message.message_id;
          renderList();
          renderDetail();
        });
        listElement.append(button);
      });
      renderDetail();
    }

    function renderSubjects(parent, subjects) {
      const section = makeElement("section", "section");
      section.append(makeElement("h2", "", "Subject analysis"));
      if (!subjects.length) {
        section.append(makeElement("div", "empty", "No subjects extracted."));
      }
      subjects.forEach(subject => {
        const card = makeElement("div", "subject-card");
        card.append(makeElement("h3", "subject-title", subject.subject_id || "Unknown subject"));
        const fields = makeElement("dl");
        Object.entries(subject).forEach(([name, value]) => {
          if (name !== "subject_id") appendField(fields, name, value);
        });
        card.append(fields);
        section.append(card);
      });
      parent.append(section);
    }

    function renderDetail() {
      detailElement.replaceChildren();
      const message = viewerData.messages.find(item => item.message_id === state.selectedId);
      if (!message) {
        detailElement.append(makeElement("p", "empty", "Select a message to see its details."));
        return;
      }

      const inner = makeElement("div", "detail-inner");
      const heading = makeElement("h2", "", `Message #${message.message_id}`);
      heading.append(" ", makeElement("span", `badge ${message.status}`, message.status));
      inner.append(heading);
      inner.append(makeElement("pre", "message-text", message.text || "(empty message)"));
      appendDataSection(inner, "Original metadata", message.original, [viewerData.text_column]);

      if (message.result) {
        const output = message.result.output;
        if (output && typeof output === "object") {
          renderSubjects(inner, Array.isArray(output.subjects) ? output.subjects : []);
          appendDataSection(inner, "Analysis output", output, ["subjects"]);
        }
        if (message.result.error) {
          const errorSection = makeElement("section", "section error-box");
          errorSection.append(makeElement("h2", "", "Processing error"));
          errorSection.append(makeElement("pre", "", displayValue(message.result.error)));
          inner.append(errorSection);
        }
        appendDataSection(inner, "Token usage", message.result.usage || {});
        appendDataSection(
          inner,
          "Processing metadata",
          message.result,
          ["output", "usage", "error", "message_id"]
        );
      } else {
        const missing = makeElement("section", "section");
        missing.append(makeElement("h2", "", "Analysis result"));
        missing.append(makeElement("div", "empty", "No result was found for this message."));
        inner.append(missing);
      }
      detailElement.append(inner);
    }

    function initialize() {
      const counts = viewerData.messages.reduce((result, message) => {
        result[message.status] = (result[message.status] || 0) + 1;
        return result;
      }, {});
      const statusSummary = Object.entries(counts).map(([key, value]) => `${key}: ${value}`).join(" · ");
      document.getElementById("summary").textContent =
        `${viewerData.messages.length} messages · ${statusSummary}`;

      const warnings = document.getElementById("warnings");
      if (viewerData.warnings.length) {
        warnings.textContent = viewerData.warnings.join(" ");
        warnings.hidden = false;
      }

      filterElement.append(new Option("All subjects", ""));
      viewerData.subjects.forEach(subject => filterElement.append(new Option(subject, subject)));
      filterElement.addEventListener("change", event => {
        state.subject = event.target.value;
        renderList();
      });
      renderList();
    }

    initialize();
  </script>
</body>
</html>
"""


def read_source_messages(
    input_file: str,
    id_column: str,
    text_column: str,
) -> list[dict[str, str]]:
    """Read source messages and validate the configured columns and IDs."""
    path = Path(input_file)
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames:
            raise ValueError(f"Source CSV has no header: {path}")
        for column in (id_column, text_column):
            if column not in reader.fieldnames:
                raise ValueError(
                    f"Source CSV {path} has no {column!r} column"
                )

        rows: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            message_id = str(row.get(id_column, ""))
            if message_id in seen_ids:
                raise ValueError(
                    f"Duplicate message ID {message_id!r} in {path} "
                    f"at line {line_number}"
                )
            seen_ids.add(message_id)
            rows.append(row)
    return rows


def read_results(results_file: str) -> dict[str, dict[str, Any]]:
    """Read JSONL results and return them indexed by message ID."""
    path = Path(results_file)
    results: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid JSON in {path} at line {line_number}: {error.msg}"
                ) from error
            if not isinstance(record, dict) or "message_id" not in record:
                raise ValueError(
                    f"Result at {path}:{line_number} must be an object with "
                    "a message_id"
                )
            message_id = str(record["message_id"])
            if message_id in results:
                raise ValueError(
                    f"Duplicate message ID {message_id!r} in {path} "
                    f"at line {line_number}"
                )
            results[message_id] = record
    return results


def result_status(record: dict[str, Any] | None) -> str:
    """Return the viewer status for a result record."""
    if record is None:
        return "missing"
    if record.get("error") or not isinstance(record.get("output"), dict):
        return "error"
    return "relevant" if record["output"].get("relevant") else "irrelevant"


def build_viewer_data(
    input_file: str,
    results_file: str,
    id_column: str = "id",
    text_column: str = "text",
) -> dict[str, Any]:
    """Join source messages with results and prepare browser-safe data."""
    rows = read_source_messages(input_file, id_column, text_column)
    results = read_results(results_file)
    source_ids = {str(row[id_column]) for row in rows}
    subjects: set[str] = set()
    messages: list[dict[str, Any]] = []

    for row in rows:
        message_id = str(row[id_column])
        record = results.get(message_id)
        message_subjects: list[str] = []
        output = record.get("output") if record else None
        if isinstance(output, dict) and isinstance(output.get("subjects"), list):
            for subject in output["subjects"]:
                if isinstance(subject, dict) and subject.get("subject_id"):
                    subject_id = str(subject["subject_id"])
                    message_subjects.append(subject_id)
                    subjects.add(subject_id)
        messages.append(
            {
                "message_id": message_id,
                "text": row.get(text_column, ""),
                "original": row,
                "result": record,
                "status": result_status(record),
                "subjects": message_subjects,
            }
        )

    orphan_ids = sorted(set(results) - source_ids)
    warnings: list[str] = []
    if orphan_ids:
        preview = ", ".join(orphan_ids[:10])
        suffix = "…" if len(orphan_ids) > 10 else ""
        warnings.append(
            f"{len(orphan_ids)} result record(s) have no matching source "
            f"message: {preview}{suffix}"
        )

    return {
        "messages": messages,
        "subjects": sorted(subjects),
        "warnings": warnings,
        "text_column": text_column,
    }


def create_app(viewer_data: dict[str, Any]) -> FastAPI:
    """Create the local FastAPI viewer application."""
    app = FastAPI(title="Telegram analysis results")
    serialized_data = json.dumps(viewer_data, ensure_ascii=False).replace(
        "<", "\\u003c"
    )

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(
            HTML_TEMPLATE.replace("__VIEWER_DATA__", serialized_data)
        )

    return app


def serve(
    input_file: str,
    results_file: str,
    id_column: str = "id",
    text_column: str = "text",
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Load result files and serve the validation UI.

    Args:
        input_file: Source CSV containing the original Telegram messages.
        results_file: JSONL file produced by ``process_messages.py``.
        id_column: CSV column containing the original message ID.
        text_column: CSV column containing the message text.
        host: Host interface for the local web server.
        port: Port for the local web server.
    """
    if port < 1 or port > 65535:
        raise ValueError("port must be between 1 and 65535")
    viewer_data = build_viewer_data(
        input_file,
        results_file,
        id_column=id_column,
        text_column=text_column,
    )
    logger.info(
        "Loaded %d messages and %d subjects; serving on http://%s:%d",
        len(viewer_data["messages"]),
        len(viewer_data["subjects"]),
        host,
        port,
    )
    uvicorn.run(create_app(viewer_data), host=host, port=port)


if __name__ == "__main__":
    add_handlers(
        logger,
        __file__,
        [DefaultConsoleHandler(), DefaultFileHandler(DEFAULT_LOG_FILE)],
    )
    fire.Fire(serve)
