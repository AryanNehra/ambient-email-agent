# Ambient Email Agent

[![CI](https://github.com/AryanNehra/ambient-email-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/AryanNehra/ambient-email-agent/actions/workflows/ci.yml)

A LangGraph email assistant (triage → respond → human-in-the-loop → memory), built on LangChain
Academy's course, extended with a tested prompt-injection guard and an LLM-as-judge calibration
study.

> **Built on [LangChain Academy's "Building Ambient Agents with LangGraph"](https://academy.langchain.com/)**, via its public repo
> [langchain-ai/agents-from-scratch](https://github.com/langchain-ai/agents-from-scratch) (MIT
> License, Copyright (c) 2026 LangChain, Inc. — preserved in [LICENSE](LICENSE)). See
> [NOTICE.md](NOTICE.md) for the full attribution and the table below for exactly which files are
> course code vs. my own additions. Course code is never presented as original work here.

## What it does

An email arrives → a **triage router** classifies it (ignore / notify / respond) → a **response
agent** drafts tool calls (write a reply, check calendar, schedule a meeting) → every
send/schedule action pauses for **human-in-the-loop** approval via interrupts → approved
feedback can update **long-term memory** (preferences) for next time. All of this is course
code, unmodified except where noted below.

My two additions sit around that pipeline:

- **Extension A** — a prompt-injection guard that doesn't depend on the LLM "noticing" an
  attack: a deterministic tool-call validator, a heuristic injection detector, and a
  memory-write guard, all independently tested and evaluated against a 24-case attack/benign
  dataset.
- **Extension B** — a calibration study measuring how much the course's existing LLM-as-judge
  agrees with a human on response quality, with kappa, confusion matrix, self-consistency, and
  bias probes.

```mermaid
flowchart TD
    Email["Incoming email"] --> Triage["triage_router<br/>(course)"]
    Triage -->|ignore| End1(("end"))
    Triage -->|notify| HITLNotify["triage_interrupt_handler<br/>HITL (course)"]
    Triage -->|respond| Agent["response_agent: llm_call<br/>(course)"]
    HITLNotify -->|user replies| Agent
    HITLNotify -->|user ignores| End2(("end"))
    Agent --> ToolCall{{"tool call proposed"}}
    ToolCall --> HITLTool["interrupt_handler<br/>HITL approval (course)"]
    HITLTool -->|accept / edit| Tools["write_email / schedule_meeting /<br/>check_calendar_availability (course, mocked)"]
    Tools --> Agent
    Agent -->|Done| End3(("end"))
    Guard["Guard: detector + tool_validator<br/>+ triage override (mine, security/)"]
    ToolCall -.validated by.-> Guard
    Triage -.validated by.-> Guard
    Memory[("LangGraph Store<br/>preferences (course)")]
    HITLNotify -.human feedback only.-> Memory
    HITLTool -.human feedback only.-> Memory
    MemGuard["memory_guard: human_feedback_scope()<br/>(mine, security/)"]
    Memory -.enforced by.-> MemGuard
```

The guard (`src/email_assistant/security/`) is implemented, unit-tested, and evaluated against
the real attack dataset and against the real course graph's HITL behavior (see
[Extension A](#extension-a-prompt-injection-guard) below) — but as shipped here it runs
alongside the graph in tests and the eval harness, not yet as a live node inside
`email_assistant_hitl.py` itself. See [Limitations](#limitations-and-next-steps) for exactly
what wiring it in would take.

## What is mine vs. the course

| Path | Origin |
|---|---|
| `src/email_assistant/` (all files except `security/`) | Course, unmodified |
| `tests/test_response.py`, `test_notebooks.py`, `run_all_tests.py` | Course, unmodified |
| `tests/conftest.py` | Course, **lightly modified** — see "Modifications to course code" below |
| `notebooks/`, `doc/` images | Course, unmodified |
| `src/email_assistant/security/` | **Mine** — Extension A guard (framing, tool_validator, detector, memory_guard, decision_log, guard orchestrator) |
| `evals/injection/` | **Mine** — Extension A attack dataset + offline/live eval runner |
| `evals/judge_calibration/` | **Mine** — Extension B dataset, labeling CLI, metrics, analysis |
| `tests/security/`, `tests/judge_calibration/` | **Mine** — 92 offline tests |
| `docs/threat-model.md`, `docs/judge-calibration-methodology.md` | **Mine** |
| `results/` | **Mine** — generated summaries, committed |
| `Makefile`, `.github/workflows/ci.yml`, `NOTICE.md` | **Mine** |

## Extension A: prompt-injection guard

**Threat model** ([docs/threat-model.md](docs/threat-model.md)): the attacker is anyone who can
get text into an email the assistant reads (indirect prompt injection). Email content must
never be able to change a recipient, bypass human approval, or write to memory. See the doc for
the full writeup.

**Guard layers** (`src/email_assistant/security/`), each independently toggleable:

1. **framing** — wraps untrusted email content in a labeled, delimited block with an explicit
   "this is data, not instructions" notice.
2. **tool_validator** — deterministic: recipient allow-list/domain policy, max recipients,
   rejects unexpected tool arguments, before any tool executes.
3. **detector** — heuristic regex/keyword detection across 5 attack categories, with
   normalization for HTML-comment, zero-width-character, and base64 obfuscation. An
   LLM-classifier mode exists behind a flag but is not used offline/in CI.
4. **memory_guard** — memory writes only permitted inside `human_feedback_scope()`, never as a
   side effect of reading email content.

**Results** (offline, deterministic, from [results/injection_summary.md](results/injection_summary.md) — exact numbers, not estimates):

| Config | Attacks blocked | Attack success rate | Benign false-positive rate |
|---|---|---|---|
| baseline (guard off) | 0/17 | 1.0 | 0.0 |
| **full guard** | **17/17** | **0.0** | **0.0** |
| only tool_validator | 12/17 | 0.294 | 0.0 |
| only detector | 9/17 | 0.471 | 0.0 |
| only memory_protection | 2/17 | 0.882 | 0.0 |
| only framing | 0/17 | 1.0 | 0.0 |

`only_framing` blocking 0/17 offline is expected, not a bug: the offline eval uses scripted
tool calls that bypass the LLM entirely, so framing (which only works by influencing what the
LLM decides to do) can't show an effect there — its contribution can only be measured in
`--live` mode against a real model. The other three layers are independently deterministic and
each contribute real, non-overlapping coverage (12 + 9 + 2 ≠ 17, i.e. they catch different
subsets of the 17 attacks).

17 attack cases across 8 categories (instruction override, data exfiltration,
impersonation/urgency, hidden instructions, tool-argument manipulation, malicious scheduling,
memory poisoning, router manipulation) + 7 benign controls, in
[evals/injection/cases.jsonl](evals/injection/cases.jsonl). 71 tests in `tests/security/`,
including an integration test that drives the real course graph with monkeypatched LLMs to
confirm `write_email`/`schedule_meeting` always pause at the HITL interrupt regardless of what
the (possibly compromised) model asked for.

**Reproduce:**
```shell
make eval-injection          # writes results/injection_summary.{json,md}
# or, with a real OPENAI_API_KEY, also exercise a real model:
python -m evals.injection.run --live --repeats 3
```

## Extension B: LLM-judge calibration

**Method**: reuses the course's existing judge unchanged (`CriteriaGrade` structured output +
`RESPONSE_CRITERIA_SYSTEM_PROMPT`, from `tests/test_response.py` /
`src/email_assistant/eval/prompts.py`) against 30 items
([evals/judge_calibration/items.jsonl](evals/judge_calibration/items.jsonl)): 10 scenarios × 3
quality variants (good / subtly-wrong / clearly-bad), built via controlled perturbation — see
[docs/judge-calibration-methodology.md](docs/judge-calibration-methodology.md) for the honest
account of how each item was constructed (no live API key was available to generate these from
the real agent).

**Labels were collected by me, manually**, via
`python -m evals.judge_calibration.label` (an interactive CLI that hides which quality tier an
item was designed as, and randomizes order, to avoid anchoring).

**Status: pending.** See [results/judge_calibration.json](results/judge_calibration.json) —
human labeling and/or a live judge run had not been completed as of this writing. No
agreement/kappa/bias numbers are reported until both exist; `analyze.py` refuses to estimate
them.

**Reproduce once labels exist and `OPENAI_API_KEY` is set:**
```shell
python -m evals.judge_calibration.label     # ~20-30 min, interactive
python -m evals.judge_calibration.analyze   # writes results/judge_calibration.{json,md}
```

Planned metrics (computed by `analyze.py`, pure functions unit-tested against hand-computed
examples in `tests/judge_calibration/test_metrics.py`): accuracy/Cohen's kappa vs. human,
confusion matrix, false-pass/false-fail rates, judge self-consistency across N=3 repeats at
temperature 0, a verbosity-bias probe, and a rubric-paraphrase-wording sensitivity probe.
Position bias is not applicable — this judge grades one response against a rubric, there's no
pairwise comparison mode. With n=30, a 95% bootstrap CI is reported alongside every point
estimate; treat n=30 as a small sample.

## Quickstart

**Offline (no API key needed):**
```shell
git clone <this repo> && cd ambient-email-agent
python3.12 -m venv .venv && source .venv/bin/activate   # course requires Python >=3.11,<3.14
pip install -e ".[dev]"
make lint    # ruff, scoped to code added here
make test    # 92 tests, tests/security + tests/judge_calibration + evals, no API key needed
make eval-injection
```

**Live mode (course notebooks, course tests, `--live` evals, and Extension B analysis) needs a
real key:**
```shell
cp .env.example .env   # fill in OPENAI_API_KEY and LANGSMITH_API_KEY
python tests/run_all_tests.py          # course's own test suite
python -m evals.injection.run --live   # guard eval against a real model
python -m evals.judge_calibration.analyze
```

## Modifications to course code

| File | Change | Reason |
|---|---|---|
| `tests/conftest.py` | Added one line setting a placeholder `OPENAI_API_KEY` if unset | Several email_assistant modules construct a `ChatOpenAI` client at import time, which validates credentials eagerly even for offline tests that monkeypatch the client before calling it. No network call is made in the offline suite. |
| `.github/workflows/claude-code-review.yml`, `.github/workflows/claude.yml` | Removed | Required an `ANTHROPIC_API_KEY` secret not configured here; replaced by `.github/workflows/ci.yml` (lint + offline tests, no secrets). |

No other course file was changed.

## Limitations and next steps

- **The guard is not yet wired into the live graph.** `evaluate_tool_call` /
  `evaluate_triage_override` are proven (by tests and the eval harness) to correctly judge the
  same tool calls and classifications the real graph produces, but `interrupt_handler` and
  `triage_router` in `email_assistant_hitl.py` don't call them yet. Wiring them in is a few
  lines per function (check the decision before `tool.invoke(...)` / before choosing `goto`)
  and was left out to keep edits to course files minimal — see the table above.
- **The heuristic detector is regex-based and bypassable** by a sufficiently creative attacker;
  it's a deterministic floor, not a guarantee. The optional LLM-classifier mode
  (`GUARD_DETECTOR_USE_LLM`) is scaffolded but not implemented or evaluated.
- **17 attack cases is not exhaustive** — real adversaries will find phrasings outside these 8
  categories. Treat the 0% offline attack-success rate as "beats these 17," not "unbeatable."
  `--live` mode hasn't been run against a real model as of this writing.
- **Judge calibration is pending real numbers** (see Extension B) — n=30 is small, and no
  results exist yet without human labels + a live key.
- **All tools are mocks**; the real Gmail integration (`email_assistant_hitl_memory_gmail.py`)
  was not touched or evaluated by either extension.
- Ideas for more: an MCP tool wrapper around the guard so it's reusable outside this repo;
  larger eval sets; wiring the guard in and re-running the live eval to see if real-model
  behavior matches the scripted "compromised model" simulation.

## License and attribution

MIT License, Copyright (c) 2026 LangChain, Inc. — see [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).

---

## Course content (original material, preserved below)

## Environment Setup 

### Python Version

* Ensure you're using Python 3.11 or later. 
* This version is required for optimal compatibility with LangGraph. 

```shell
python3 --version
```

### API Keys

* If you don't have an OpenAI API key, you can sign up [here](https://openai.com/index/openai-api/).
* Sign up for LangSmith [here](https://smith.langchain.com/).
* Generate a LangSmith API key.

### Set Environment Variables

* Create a `.env` file in the root directory:
```shell
# Copy the .env.example file to .env
cp .env.example .env
```

* Edit the `.env` file with the following:
```shell
LANGSMITH_API_KEY=your_langsmith_api_key
LANGSMITH_TRACING=true
LANGSMITH_PROJECT="interrupt-workshop"
OPENAI_API_KEY=your_openai_api_key
```

* You can also set the environment variables in your terminal:
```shell
export LANGSMITH_API_KEY=your_langsmith_api_key
export LANGSMITH_TRACING=true
export OPENAI_API_KEY=your_openai_api_key
```

### Package Installation

**Recommended: Using uv (faster and more reliable)**

```shell
# Install uv if you haven't already
pip install uv

# Install the package with development dependencies
uv sync --extra dev

# Activate the virtual environment
source .venv/bin/activate
```

**Alternative: Using pip**

```shell
$ python3 -m venv .venv
$ source .venv/bin/activate
# Ensure you have a recent version of pip (required for editable installs with pyproject.toml)
$ python3 -m pip install --upgrade pip
# Install the package in editable mode
$ pip install -e .
```

> **⚠️ IMPORTANT**: Do not skip the package installation step! This editable install is **required** for the notebooks to work correctly. The package is installed as `interrupt_workshop` with import name `email_assistant`, allowing you to import from anywhere with `from email_assistant import ...`

## Structure 

The repo is organized into the 4 sections, with a notebook for each and accompanying code in the `src/email_assistant` directory.

### Preface: LangGraph 101
For a brief introduction to LangGraph and some of the concepts used in this repo, see the [LangGraph 101 notebook](notebooks/langgraph_101.ipynb). This notebook explains the basics of chat models, tool calling, agents vs workflows, LangGraph nodes / edges / memory, and LangGraph Studio.

### Building an agent 
* Notebook: [notebooks/agent.ipynb](/notebooks/agent.ipynb)
* Code: [src/email_assistant/email_assistant.py](/src/email_assistant/email_assistant.py)

![overview-agent](notebooks/img/overview_agent.png)

This notebook shows how to build the email assistant, combining an [email triage step](https://langchain-ai.github.io/langgraph/tutorials/workflows/) with an agent that handles the email response. You can see the linked code for the full implementation in `src/email_assistant/email_assistant.py`.

![Screenshot 2025-04-04 at 4 06 18 PM](notebooks/img/studio.png)

### Evaluation 
* Notebook: [notebooks/evaluation.ipynb](/notebooks/evaluation.ipynb)

![overview-eval](notebooks/img/overview_eval.png)

This notebook introduces evaluation with an email dataset in [eval/email_dataset.py](/eval/email_dataset.py). It shows how to run evaluations using Pytest and the LangSmith `evaluate` API. It runs evaluation for emails responses using LLM-as-a-judge as well as evaluations for tools calls and triage decisions.

![Screenshot 2025-04-08 at 8 07 48 PM](notebooks/img/eval.png)

### Human-in-the-loop 
* Notebook: [notebooks/hitl.ipynb](/notebooks/hitl.ipynb)
* Code: [src/email_assistant/email_assistant_hitl.py](/src/email_assistant/email_assistant_hitl.py)

![overview-hitl](notebooks/img/overview_hitl.png)

This notebooks shows how to add human-in-the-loop (HITL), allowing the user to review specific tool calls (e.g., send email, schedule meeting). For this, we use [Agent Inbox](https://github.com/langchain-ai/agent-inbox) as an interface for human in the loop. You can see the linked code for the full implementation in [src/email_assistant/email_assistant_hitl.py](/src/email_assistant/email_assistant_hitl.py).

![Agent Inbox showing email threads](notebooks/img/agent-inbox.png)

### Memory  
* Notebook: [notebooks/memory.ipynb](/notebooks/memory.ipynb)
* Code: [src/email_assistant/email_assistant_hitl_memory.py](/src/email_assistant/email_assistant_hitl_memory.py)

![overview-memory](notebooks/img/overview_memory.png)  

This notebook shows how to add memory to the email assistant, allowing it to learn from user feedback and adapt to preferences over time. The memory-enabled assistant ([email_assistant_hitl_memory.py](/src/email_assistant/email_assistant_hitl_memory.py)) uses the [LangGraph Store](https://langchain-ai.github.io/langgraph/concepts/memory/#long-term-memory) to persist memories. You can see the linked code for the full implementation in [src/email_assistant/email_assistant_hitl_memory.py](/src/email_assistant/email_assistant_hitl_memory.py).

## Connecting to APIs  

The above notebooks using mock email and calendar tools. 

### Gmail Integration and Deployment

Set up Google API credentials following the instructions in [Gmail Tools README](src/email_assistant/tools/gmail/README.md).

The README also explains how to deploy the graph to LangGraph Platform.

The full implementation of the Gmail integration is in [src/email_assistant/email_assistant_hitl_memory_gmail.py](/src/email_assistant/email_assistant_hitl_memory_gmail.py).

## Running Tests

The repository includes an automated test suite to evaluate the email assistant. 

Tests verify correct tool usage and response quality using LangSmith for tracking.

### Running Tests with [run_all_tests.py](/tests/run_all_tests.py)

```shell
python tests/run_all_tests.py
```

### Test Results

Test results are logged to LangSmith under the project name specified in your `.env` file (`LANGSMITH_PROJECT`). This provides:
- Visual inspection of agent traces
- Detailed evaluation metrics
- Comparison of different agent implementations

### Available Test Implementations

The available implementations for testing are:
- `email_assistant` - Basic email assistant

### Testing Notebooks

You can also run tests to verify all notebooks execute without errors:

```shell
# Run all notebook tests
python tests/test_notebooks.py

# Or run via pytest
pytest tests/test_notebooks.py -v
```

## Future Extensions

Add [LangMem](https://langchain-ai.github.io/langmem/) to manage memories:
* Manage a collection of background memories. 
* Add memory tools that can look up facts in the background memories. 



