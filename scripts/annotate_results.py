"""Review Telegram analysis results and store feedback in Markdown."""

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

import fire
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from logkittt.core import add_handlers, get_logger
from logkittt.handlers import DefaultConsoleHandler, DefaultFileHandler

from visualize_results import build_viewer_data


logger = get_logger("could_llm_help", __name__)

DEFAULT_LOG_FILE = str(
    Path(__file__).resolve().parents[1] / "logs" / "annotate_results.log"
)
FEEDBACK_TITLE = "# Telegram message feedback"


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Telegram feedback annotator</title>
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
      --success: #18794e;
      --relevant: #18794e;
      --irrelevant: #667085;
      --error: #b42318;
      --missing: #b54708;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      display: flex;
      flex-direction: column;
      margin: 0;
      background: var(--bg);
      color: var(--text);
    }
    button, select, textarea, input { font: inherit; }
    header {
      padding: 16px 24px;
      background: var(--panel);
      border-bottom: 1px solid var(--border);
    }
    h1 { margin: 0 0 4px; font-size: 22px; }
    h2 { margin: 0 0 12px; font-size: 18px; }
    h3 { margin: 14px 0 7px; font-size: 14px; }
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
      flex: 1;
      grid-template-columns: minmax(290px, 370px) minmax(0, 1fr);
      min-height: 0;
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
    select, textarea {
      width: 100%;
      padding: 9px 10px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: #fff;
    }
    .visible-count { margin-top: 8px; color: var(--muted); font-size: 12px; }
    .message-list { overflow-y: auto; padding-bottom: 14px; }
    .list-heading {
      position: sticky;
      top: 0;
      z-index: 1;
      margin: 0;
      padding: 9px 14px;
      background: #eef1f5;
      color: #344054;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .message-item {
      display: block;
      width: 100%;
      padding: 11px 14px;
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
    .message-id { font-weight: 650; font-size: 13px; overflow-wrap: anywhere; }
    .badge {
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
    .excerpt {
      display: -webkit-box;
      margin-top: 6px;
      overflow: hidden;
      color: #344054;
      font-size: 13px;
      line-height: 1.35;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
    }
    .empty { padding: 12px 14px; color: var(--muted); font-style: italic; }
    .detail {
      display: flex;
      flex-direction: column;
      min-width: 0;
      min-height: 0;
      overflow: hidden;
    }
    .detail-inner { max-width: 1000px; margin: 0 auto; }
    .message-panel {
      flex: 0 0 auto;
      padding: 18px clamp(18px, 4vw, 52px) 14px;
      background: var(--bg);
      border-bottom: 1px solid var(--border);
    }
    .detail-scroll {
      flex: 1 1 auto;
      min-height: 0;
      overflow-y: auto;
      padding: 0 clamp(18px, 4vw, 52px) 24px;
    }
    .feedback-panel {
      flex: 0 0 auto;
      padding: 12px clamp(18px, 4vw, 52px) 14px;
      background: var(--bg);
      border-top: 1px solid var(--border);
      box-shadow: 0 -4px 12px rgba(24, 33, 47, 0.08);
    }
    .message-heading { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
    .message-link { color: var(--accent); font-size: 13px; }
    .message-text {
      margin: 0;
      padding: 16px;
      max-height: 34vh;
      overflow-y: auto;
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
    .feedback-section { margin-top: 0; }
    .feedback-row { display: flex; justify-content: space-between; gap: 16px; align-items: center; }
    .validated-label { display: flex; gap: 7px; align-items: center; margin: 0; color: var(--text); }
    textarea { min-height: 84px; max-height: 24vh; resize: vertical; line-height: 1.45; }
    .save-status { min-height: 20px; margin-top: 7px; color: var(--muted); font-size: 12px; }
    .save-status.saved { color: var(--success); }
    .save-status.failed { color: var(--error); }
    .subject-card { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border); }
    .subject-card:first-of-type { margin-top: 0; padding-top: 0; border-top: 0; }
    .subject-title { margin: 0 0 8px; color: var(--accent); }
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
    .chip { padding: 2px 7px; border-radius: 999px; background: #edf1f5; font-size: 11px; }
    .error-box { color: var(--error); }
    @media (max-width: 760px) {
      .layout { grid-template-columns: 1fr; overflow-y: auto; }
      .sidebar { height: 42vh; border-right: 0; border-bottom: 1px solid var(--border); }
      .detail { min-height: 100vh; }
      .message-panel { padding: 18px 14px 14px; }
      .detail-scroll { padding: 0 14px 24px; }
      .feedback-panel { padding: 12px 14px 14px; }
      .field { grid-template-columns: 1fr; gap: 3px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Telegram feedback annotator</h1>
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
    const state = {
      subject: "",
      selectedId: null,
      dirty: false,
      editVersion: 0,
      savePromise: null
    };
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

    function notesFromTextarea() {
      const textarea = document.getElementById("feedback-notes");
      if (!textarea) return [];
      return textarea.value.split(/\r?\n/).filter(line => line.trim());
    }

    function setSaveStatus(text, className = "") {
      const indicator = document.getElementById("save-status");
      if (!indicator) return;
      indicator.textContent = text;
      indicator.className = `save-status ${className}`;
    }

    async function patchFeedback(messageId, changes) {
      const response = await fetch("/api/feedback", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: messageId, ...changes })
      });
      let body = {};
      try { body = await response.json(); } catch (_) { /* response was not JSON */ }
      if (!response.ok) throw new Error(body.detail || `Save failed (${response.status})`);
      return body;
    }

    async function flushNotes() {
      if (!state.dirty) return true;
      if (state.savePromise) {
        const saved = await state.savePromise;
        if (!saved) return false;
        return state.dirty ? flushNotes() : true;
      }
      const message = viewerData.messages.find(item => item.message_id === state.selectedId);
      if (!message) return true;
      const editVersion = state.editVersion;
      const notes = notesFromTextarea();
      setSaveStatus("Saving…");
      state.savePromise = (async () => {
        try {
          const feedback = await patchFeedback(message.message_id, { notes });
          message.feedback = feedback;
          if (state.selectedId === message.message_id && state.editVersion === editVersion) {
            state.dirty = false;
          }
          setSaveStatus("Saved", "saved");
          return true;
        } catch (error) {
          setSaveStatus(error.message || "Save failed", "failed");
          return false;
        }
      })();
      const saved = await state.savePromise;
      state.savePromise = null;
      if (!saved) return false;
      return state.dirty ? flushNotes() : true;
    }

    async function selectMessage(messageId) {
      if (messageId === state.selectedId) return;
      if (!(await flushNotes())) return;
      state.selectedId = messageId;
      state.dirty = false;
      renderList();
      renderDetail();
    }

    function renderList() {
      const messages = filteredMessages();
      const tbd = messages.filter(message => !message.feedback.validated);
      const done = messages.filter(message => message.feedback.validated);
      document.getElementById("visible-count").textContent =
        `${messages.length} of ${viewerData.messages.length} messages`;
      listElement.replaceChildren();

      [["TBD", tbd], ["Done", done]].forEach(([title, items]) => {
        listElement.append(makeElement("h2", "list-heading", `${title} (${items.length})`));
        if (!items.length) {
          listElement.append(makeElement("div", "empty", "No messages"));
          return;
        }
        items.forEach(message => {
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
          button.addEventListener("click", () => selectMessage(message.message_id));
          listElement.append(button);
        });
      });
    }

    function renderSubjects(parent, subjects) {
      const section = makeElement("section", "section");
      section.append(makeElement("h2", "", "Subject analysis"));
      if (!subjects.length) section.append(makeElement("div", "empty", "No subjects extracted."));
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
      const messagePanel = makeElement("div", "message-panel");
      const messageInner = makeElement("div", "detail-inner");
      const headingRow = makeElement("div", "message-heading");
      const heading = makeElement("h2", "", `Message #${message.message_id}`);
      heading.append(" ", makeElement("span", `badge ${message.status}`, message.status));
      headingRow.append(heading);
      const sourceName = String(message.original.source || "").trim().replace(/^@/, "");
      const sourceMessageId = String(message.original.id || "").trim();
      if (sourceName && sourceMessageId) {
        const link = makeElement("a", "message-link", "Open message in Telegram");
        link.href = `https://t.me/${encodeURIComponent(sourceName)}/${encodeURIComponent(sourceMessageId)}`;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        headingRow.append(link);
      }
      messageInner.append(headingRow);
      messageInner.append(
        makeElement("pre", "message-text", message.text || "(empty message)")
      );
      messagePanel.append(messageInner);
      detailElement.append(messagePanel);

      const detailScroll = makeElement("div", "detail-scroll");
      const inner = makeElement("div", "detail-inner");

      const feedbackSection = makeElement("section", "section feedback-section");
      const feedbackRow = makeElement("div", "feedback-row");
      feedbackRow.append(makeElement("h2", "", "Feedback"));
      const validatedLabel = makeElement("label", "validated-label");
      const checkbox = makeElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = message.feedback.validated;
      validatedLabel.append(checkbox, " Validated");
      feedbackRow.append(validatedLabel);
      feedbackSection.append(feedbackRow);
      const textarea = makeElement("textarea");
      textarea.id = "feedback-notes";
      textarea.placeholder = "One feedback item per line";
      textarea.value = message.feedback.notes.join("\n");
      textarea.addEventListener("input", () => {
        state.dirty = true;
        state.editVersion += 1;
        setSaveStatus("");
      });
      textarea.addEventListener("keydown", event => {
        if (event.key === "Enter" && !event.shiftKey) setTimeout(flushNotes, 0);
      });
      textarea.addEventListener("blur", flushNotes);
      feedbackSection.append(textarea);
      const saveStatus = makeElement("div", "save-status");
      saveStatus.id = "save-status";
      feedbackSection.append(saveStatus);
      checkbox.addEventListener("change", async () => {
        const requested = checkbox.checked;
        checkbox.disabled = true;
        if (!(await flushNotes())) {
          checkbox.checked = message.feedback.validated;
          checkbox.disabled = false;
          return;
        }
        setSaveStatus("Saving…");
        try {
          const feedback = await patchFeedback(message.message_id, { validated: requested });
          message.feedback = feedback;
          setSaveStatus("Saved", "saved");
          renderList();
        } catch (error) {
          checkbox.checked = message.feedback.validated;
          setSaveStatus(error.message || "Save failed", "failed");
        } finally {
          checkbox.disabled = false;
        }
      });
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
          inner, "Processing metadata", message.result,
          ["output", "usage", "error", "message_id"]
        );
      } else {
        const missing = makeElement("section", "section");
        missing.append(makeElement("h2", "", "Analysis result"));
        missing.append(makeElement("div", "empty", "No result was found for this message."));
        inner.append(missing);
      }
      appendDataSection(inner, "Original metadata", message.original, [viewerData.text_column]);
      detailScroll.append(inner);
      detailElement.append(detailScroll);

      const feedbackPanel = makeElement("div", "feedback-panel");
      const feedbackInner = makeElement("div", "detail-inner");
      feedbackInner.append(feedbackSection);
      feedbackPanel.append(feedbackInner);
      detailElement.append(feedbackPanel);
    }

    async function changeFilter(value) {
      if (!(await flushNotes())) {
        filterElement.value = state.subject;
        return;
      }
      state.subject = value;
      const messages = filteredMessages();
      if (!messages.some(message => message.message_id === state.selectedId)) {
        state.selectedId = messages.length ? messages[0].message_id : null;
      }
      renderList();
      renderDetail();
    }

    function initialize() {
      const done = viewerData.messages.filter(message => message.feedback.validated).length;
      document.getElementById("summary").textContent =
        `${viewerData.messages.length} messages · TBD: ${viewerData.messages.length - done} · Done: ${done}`;
      const warnings = document.getElementById("warnings");
      if (viewerData.warnings.length) {
        warnings.textContent = viewerData.warnings.join(" ");
        warnings.hidden = false;
      }
      filterElement.append(new Option("All subjects", ""));
      viewerData.subjects.forEach(subject => filterElement.append(new Option(subject, subject)));
      filterElement.addEventListener("change", event => changeFilter(event.target.value));
      state.selectedId = viewerData.messages.length ? viewerData.messages[0].message_id : null;
      renderList();
      renderDetail();
    }
    initialize();
  </script>
</body>
</html>
"""


def validate_feedback_path(feedback_file: str) -> Path:
    """Validate the feedback path and its prompt-folder dependencies."""
    path = Path(feedback_file)
    if path.suffix.lower() != ".md":
        raise ValueError("feedback_file must have a .md extension")
    for filename in ("shared-prompt.md", "output_schema.py"):
        required_path = path.parent / filename
        if not required_path.is_file():
            raise ValueError(
                f"Feedback folder {path.parent} must contain {filename}"
            )
    return path


def parse_feedback(content: str, path: Path) -> dict[str, dict[str, Any]]:
    """Parse canonical feedback Markdown and reject unsupported content."""
    lines = content.splitlines()
    if not lines or lines[0] != FEEDBACK_TITLE:
        raise ValueError(f"{path}:1 must be exactly {FEEDBACK_TITLE!r}")

    records: dict[str, dict[str, Any]] = {}
    index = 1
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        line_number = index + 1
        if not lines[index].startswith("## ") or not lines[index][3:].strip():
            raise ValueError(
                f"Unsupported content in {path} at line {line_number}: "
                f"expected a '## message-id' heading"
            )
        current_id = lines[index][3:].strip()
        if current_id in records:
            raise ValueError(
                f"Duplicate message ID {current_id!r} in {path} "
                f"at line {line_number}"
            )
        index += 1
        if index >= len(lines) or lines[index] not in ("status: [x]", "status: [ ]"):
            status_line = index + 1
            raise ValueError(
                f"Invalid or missing status in {path} at line {status_line}; "
                "expected 'status: [x]' or 'status: [ ]'"
            )
        validated = lines[index] == "status: [x]"
        index += 1
        notes: list[str] = []
        while index < len(lines) and not lines[index].startswith("## "):
            if not lines[index].strip():
                index += 1
                continue
            if not lines[index].startswith("- ") or not lines[index][2:].strip():
                raise ValueError(
                    f"Unsupported content in {path} at line {index + 1}: "
                    "expected a non-empty Markdown bullet"
                )
            notes.append(lines[index][2:])
            index += 1
        records[current_id] = {"notes": notes, "validated": validated}
    return records


def read_feedback(path: Path) -> dict[str, dict[str, Any]]:
    """Read and parse an existing feedback file."""
    return parse_feedback(path.read_text(encoding="utf-8"), path)


def serialize_feedback(records: dict[str, dict[str, Any]]) -> str:
    """Serialize feedback records in their insertion order."""
    sections = [FEEDBACK_TITLE]
    for current_id, record in records.items():
        status = "x" if record["validated"] else " "
        lines = [f"## {current_id}", f"status: [{status}]"]
        notes = record["notes"]
        if notes:
            lines.append("")
            lines.extend(f"- {note}" for note in notes)
        sections.append("\n".join(lines))
    return "\n\n".join(sections) + "\n"


def write_feedback(path: Path, records: dict[str, dict[str, Any]]) -> None:
    """Atomically replace a feedback file with canonical Markdown."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as target:
            temporary_path = Path(target.name)
            target.write(serialize_feedback(records))
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def initialize_feedback(
    path: Path,
    message_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Create feedback or append missing messages after validating it."""
    records = read_feedback(path) if path.exists() else {}
    changed = not path.exists()
    for current_id in message_ids:
        if current_id not in records:
            records[current_id] = {"notes": [], "validated": False}
            changed = True
    if changed:
        write_feedback(path, records)
    return records


def prompt_version_warnings(
    prompt_folder_name: str,
    messages: list[dict[str, Any]],
) -> list[str]:
    """Return warnings for result prompt versions that differ from the folder."""
    versions = {
        str(message["result"]["prompt_version"])
        for message in messages
        if message.get("result")
        and message["result"].get("prompt_version") is not None
    }
    mismatches = sorted(
        version for version in versions if version != prompt_folder_name
    )
    if not mismatches:
        return []
    return [
        f"Feedback folder is {prompt_folder_name!r}, but result prompt version(s) "
        f"include: {', '.join(mismatches)}"
    ]


def feedback_warnings(
    records: dict[str, dict[str, Any]],
    source_ids: set[str],
) -> list[str]:
    """Return a warning for preserved records absent from the source CSV."""
    orphan_ids = [current_id for current_id in records if current_id not in source_ids]
    if not orphan_ids:
        return []
    preview = ", ".join(orphan_ids[:10])
    suffix = "…" if len(orphan_ids) > 10 else ""
    return [
        f"{len(orphan_ids)} feedback record(s) are not in the current source CSV "
        f"and were preserved: {preview}{suffix}"
    ]


def attach_feedback(
    viewer_data: dict[str, Any],
    records: dict[str, dict[str, Any]],
    prompt_folder_name: str,
) -> dict[str, Any]:
    """Attach current feedback and warnings to browser data."""
    source_ids = {message["message_id"] for message in viewer_data["messages"]}
    for message in viewer_data["messages"]:
        message["feedback"] = records[message["message_id"]]
    viewer_data["warnings"] = list(viewer_data["warnings"])
    viewer_data["warnings"].extend(
        prompt_version_warnings(prompt_folder_name, viewer_data["messages"])
    )
    viewer_data["warnings"].extend(feedback_warnings(records, source_ids))
    return viewer_data


def validate_notes(value: Any) -> list[str]:
    """Validate notes received by the feedback endpoint."""
    if not isinstance(value, list):
        raise ValueError("notes must be a list of non-empty strings")
    notes: list[str] = []
    for index, note in enumerate(value):
        if (
            not isinstance(note, str)
            or not note.strip()
            or "\n" in note
            or "\r" in note
        ):
            raise ValueError(
                f"notes[{index}] must be a non-empty single-line string"
            )
        notes.append(note)
    return notes


def create_app(
    viewer_data: dict[str, Any],
    feedback_path: Path,
) -> FastAPI:
    """Create the annotation application."""
    app = FastAPI(title="Telegram feedback annotator")
    write_lock = threading.Lock()
    current_id_list = [
        message["message_id"] for message in viewer_data["messages"]
    ]
    current_ids = set(current_id_list)

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        with write_lock:
            records = initialize_feedback(feedback_path, current_id_list)
        page_data = attach_feedback(
            json.loads(json.dumps(viewer_data)),
            records,
            feedback_path.parent.name,
        )
        serialized_data = json.dumps(page_data, ensure_ascii=False).replace(
            "<", "\\u003c"
        )
        return HTMLResponse(
            HTML_TEMPLATE.replace("__VIEWER_DATA__", serialized_data)
        )

    @app.patch("/api/feedback")
    def update_feedback(payload: dict[str, Any]) -> dict[str, Any]:
        allowed_keys = {"message_id", "notes", "validated"}
        if set(payload) - allowed_keys:
            raise HTTPException(status_code=422, detail="Unsupported request field")
        current_id = payload.get("message_id")
        if not isinstance(current_id, str) or current_id not in current_ids:
            raise HTTPException(status_code=404, detail="Unknown current message_id")
        if "notes" not in payload and "validated" not in payload:
            raise HTTPException(
                status_code=422,
                detail="Provide notes and/or validated",
            )
        try:
            notes = validate_notes(payload["notes"]) if "notes" in payload else None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        validated = payload.get("validated")
        if "validated" in payload and not isinstance(validated, bool):
            raise HTTPException(status_code=422, detail="validated must be a boolean")

        with write_lock:
            try:
                records = read_feedback(feedback_path)
                record = records.get(
                    current_id,
                    {"notes": [], "validated": False},
                )
                if notes is not None:
                    record["notes"] = notes
                if "validated" in payload:
                    record["validated"] = validated
                records[current_id] = record
                write_feedback(feedback_path, records)
            except (OSError, ValueError) as error:
                logger.exception("Failed to update feedback for %s", current_id)
                raise HTTPException(status_code=500, detail=str(error)) from error
        return record

    return app


def serve(
    input_file: str,
    results_file: str,
    feedback_file: str,
    text_column: str = "text",
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Load source data and serve the feedback annotation UI."""
    if port < 1 or port > 65535:
        raise ValueError("port must be between 1 and 65535")
    feedback_path = validate_feedback_path(feedback_file)
    viewer_data = build_viewer_data(
        input_file,
        results_file,
        text_column=text_column,
    )
    message_ids = [message["message_id"] for message in viewer_data["messages"]]
    records = initialize_feedback(feedback_path, message_ids)
    startup_data = attach_feedback(
        json.loads(json.dumps(viewer_data)),
        records,
        feedback_path.parent.name,
    )
    for warning in startup_data["warnings"]:
        logger.warning(warning)
    logger.info(
        "Loaded %d messages; serving on http://%s:%d",
        len(message_ids),
        host,
        port,
    )
    uvicorn.run(create_app(viewer_data, feedback_path), host=host, port=port)


if __name__ == "__main__":
    add_handlers(
        logger,
        __file__,
        [DefaultConsoleHandler(), DefaultFileHandler(DEFAULT_LOG_FILE)],
    )
    fire.Fire(serve)
