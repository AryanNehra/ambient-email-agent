# Notice

This project is built on top of [langchain-ai/agents-from-scratch](https://github.com/langchain-ai/agents-from-scratch),
LangChain Academy's course material for "Building Ambient Agents with LangGraph".

```
MIT License

Copyright (c) 2026 LangChain, Inc.
```

The full license text is preserved in [LICENSE](LICENSE).

## What is course code vs. original work

See the "What is mine vs. the course" table in [README.md](README.md) for the file-by-file
breakdown. In summary:

- `src/email_assistant/` (minus `src/email_assistant/security/`), `notebooks/`, `tests/test_notebooks.py`,
  `tests/test_response.py`, `tests/run_all_tests.py`, `tests/conftest.py` are from the course,
  unmodified or lightly modified (see "Modifications to course code" in the README).
- `src/email_assistant/security/`, `evals/`, `docs/`, `results/`, and the CI/tooling config
  (`Makefile`, `.github/workflows/ci.yml`, this file) are original work added for this project.

No course code is presented as original work by the author of this repository.
