#!/usr/bin/env python

import os
import pytest
import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

# Several email_assistant modules construct a ChatOpenAI client at import time
# (e.g. `init_chat_model("openai:gpt-4.1")` at module scope), which validates
# credentials eagerly even though offline tests monkeypatch the client before
# ever calling `.invoke()`. Set a placeholder key so those imports succeed
# without a real key; no network call is ever made in offline tests.
os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder-not-a-real-key")

def pytest_addoption(parser):
    """Add command-line options to pytest."""
    parser.addoption(
        "--agent-module", 
        action="store", 
        default="email_assistant_hitl_memory",
        help="Specify which email assistant module to test"
    )

@pytest.fixture(scope="session")
def agent_module_name(request):
    """Return the agent module name from command line."""
    return request.config.getoption("--agent-module")