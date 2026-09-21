---
name: iterate-prompt-from-feedback
description: Analyze prompt feedback with matched test messages and JSONL results, propose evidence-based improvements, and create an approved next prompt version with a concise iteration note. Use when iterating prompts under prompts/v*/ from evaluation feedback.
---

# Iterate Prompt From Feedback

Improve this project's structured-extraction prompt without overwriting prior
versions or turning isolated feedback into unnecessary general rules.

## Inspect the evaluation set

1. Read `docs/prompt-guidelines.md`. Read `docs/implementation.md` only when
   implementation details affect the task.
2. Use the prompt version named by the user. If none is named, identify the
   latest version that has feedback and results. Inspect both
   `shared-prompt.md` and `output_schema.py`.
3. Match files by basename:
   - `prompts/<version>/feedback/<name>.md`
   - `prompts/<version>/results/<name>.jsonl`
   - `data/test/<name>.csv`
4. Access no files under `data/` except `data/test/`. Respect all other
   repository restrictions in `AGENTS.md`.
5. Extract general feedback appearing before the first message heading and
   per-message notes under headings such as `source/id`. Treat status markers
   as review metadata, not as corrections by themselves.
6. Build the input message key as `<source>/<id>` from the CSV and join it to
   JSONL `message_id` and the feedback heading. Report missing, duplicate, or
   unmatched records before drawing conclusions.

## Analyze before editing

For every note, compare all four sources:

- original message text;
- generated structured output;
- feedback note;
- current shared prompt and schema.

Group findings into:

- prompt boundary or instruction changes;
- schema subject or enum changes;
- errors caused by subject-local stance, portrayal, harm, or evidence leakage;
- filtering or pipeline ideas that do not require a prompt change;
- positive examples confirming existing behavior;
- ambiguous or mutually inconsistent feedback requiring an explicit policy
  choice.

Prefer a small general rule that explains multiple errors. Do not blindly
encode every example, add categories from tentative notes without calling out
the decision, or inflate the prompt with examples for behavior that already
worked. Identify conflicts between feedback and existing rules explicitly.

Return a prioritized list of suggested changes with representative
`message_id` evidence. Separate recommended defaults from decisions the user
must make. Do not edit files during this analysis phase.

## Approval and version creation

Use two distinct approval stages:

1. Obtain agreement on the proposed semantic and schema changes.
2. Then name every file to be created or edited, summarize the exact changes,
   ask a standalone approval question, and wait for a clear affirmative answer.

The original request and agreement on recommendations are not file-edit
permission. Do not make any file change before the second approval.

After approval:

1. Create the next consecutive `prompts/vN/` directory according to
   `docs/prompt-guidelines.md`.
2. Create exactly:
   - `shared-prompt.md` beginning with the role instruction;
   - `output_schema.py` defining the Pydantic structured output;
   - `iterate-note.md` recording the evaluation basis, agreed changes, prompt
     size before and after, validation results, and unresolved policy choices.
3. Base the prompt and schema on the reviewed version and apply only agreed
   changes.
4. Preserve all earlier prompt versions unchanged.
5. Keep `iterate-note.md` concise. Record join integrity and dataset basenames,
   but do not copy message text or dump raw feedback into it.
6. Do not create feedback, results, other documentation, or migration files
   unless separately requested and approved.
7. Never commit changes.

## Verify

- Import the new schema with bytecode writing disabled and exercise its model
  validators with a minimal valid object.
- Confirm added and removed enum values match the agreement.
- Check that the prompt follows `docs/prompt-guidelines.md` and that only the
  approved files changed.
- Confirm `iterate-note.md` accurately records the completed analysis and
  verification, including unavailable checks and any unresolved choice.
- Run a non-mutating formatting or diff check when available.
- Report created files, prompt-size change, validation results, and any
  unresolved policy choice.
