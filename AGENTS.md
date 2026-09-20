# Process Telegram Messages with LLM
# Overview
Goal is to extract structured infomation from Telegram messages that would help to build social portrait for a certian groups in future.

This project is a part of more general task about monitoring of how different social groups are represented in social media.
General workflow is:
  collecting Telegram message -> get structured observations (current project) -> aggregate by group/channel/time -> build analytical  social portrait.

Detailed information on how extracted data will be aggreagted into social portraits is TBD.

# Implementation plan/details.
Please load implementation plan from `docs/implementation.md` into context if needed.
Prompt guidelines - `docs/prompt-guidelines.md`


## Build, test, dev commands
you are in a conda env.
there is a python available with pre-installed libs.
you can check available packages by `pip freeze`. 
in case you need to install package ask me to do that. 
do not operate conda env by youself.

## Coding Style and Naming Conventions
- keep code simple, do not overthink, especially with testing.
- Follow PEP 8: 4-space indentation, snake_case for functions/variables, PascalCase for classes.
- Google-style docstrings if needed.
- for print/logs use logkit lib (available in current env)
- for parsing cli params use fire
- use yaml as config format that are expected to edit by human
- use json for computer readed configs.

## OpenAI API usage
api key is available in `OPENAI_API_KEY` env var.

## Edit permission and restrictions (strict)
Before making any file change, the agent MUST:

1. Propose the exact files to edit and a short summary of planned changes.
2. Ask for explicit approval in a standalone question.
3. Wait for a clear yes from me before running any edit command.

A user request like “please fix it” or “do X” is NOT permission to edit files by itself.
Permission is granted only when I explicitly confirm after the proposal (for example: “Yes, apply these changes”).

If explicit approval is missing, the agent may only do read-only actions
(inspect files, search, explain, propose diffs).

Agent DOES NOT commit any changes to git at all.
Only in a read mode for commands like status or diff

## Restricted files

Do not read, inspect, search, modify, or otherwise access:
- data/* except of data/test/* subfolder
- notes/*
- archive/*
- export_openai_api_key.sh
