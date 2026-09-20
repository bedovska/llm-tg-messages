### Prompt guidelines
- The shared prompt should begin with the role instruction.
- Keep the role instruction in the shared prompt rather than hard-coding it in the processing script.
- keep prompt as small as possible, do not iflate it with useless text
- use `Subject boundaries` section to describe differences between subjects or subject particular properties, that is hard to get from the name itself

- every prompt consists of two files:
  - shared-prompt.md
  - output_schema.py -> descirbe structured output with pydantic

- prompt are stored under prompts/ folder.
- new prompts should be saved into a prompts/v{} subfolder, where v{} should be a next consequtive version based on available in prompt folder.


