# agentpay `request_payment` Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `request_payment` tool to the kaji Python SDK that calls `POST /v1/sessions` on `@agentpay/api` and returns a checkout URL to the agent.

**Architecture:** The tool lives in `packages/sdk/kaji/tools/payment.py`. It registers itself with kaji's tool registry using the existing `register_tool` + `ToolSpec` pattern. Configuration (API base URL, API key) is read from env vars at call time. The tool is opt-in — nothing imports it by default; callers register it by importing the module.

**Tech Stack:** Python 3.11+, `httpx` (already a SDK dep), `kaji.runtime.tools.registry`.

**Dependency:** Requires Plan 1 (agentpay API extensions) deployed — the tool calls `POST /v1/sessions`.

---

## File Map

| file | action | responsibility |
|------|--------|---------------|
| `packages/sdk/kaji/tools/__init__.py` | create | empty package marker |
| `packages/sdk/kaji/tools/payment.py` | create | `request_payment` tool + registration helper |
| `packages/sdk/tests/test_tools_payment.py` | create | unit tests (mocked HTTP) |

---

## Task 1: Package scaffold

**Files:**
- Create: `packages/sdk/kaji/tools/__init__.py`

- [ ] **Step 1: Create the package**

```bash
mkdir -p packages/sdk/kaji/tools
touch packages/sdk/kaji/tools/__init__.py
```

- [ ] **Step 2: Verify importable**

```bash
cd packages/sdk && python -c "import kaji.tools; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add packages/sdk/kaji/tools/__init__.py
git commit -m "feat(sdk): add kaji.tools package"
```

---

## Task 2: Write the failing tests

**Files:**
- Create: `packages/sdk/tests/test_tools_payment.py`

- [ ] **Step 1: Write the failing test**

Create `packages/sdk/tests/test_tools_payment.py`:

```python
"""Tests for the request_payment agentpay tool."""

import pytest
import httpx
from unittest.mock import patch, AsyncMock, MagicMock

from kaji.runtime.tools.registry import (
    ToolContext,
    _TOOL_SPECS,
    _TOOL_HANDLERS,
)


@pytest.fixture(autouse=True)
def isolated_registry():
    """Reset the tool registry between tests."""
    saved_specs = dict(_TOOL_SPECS)
    saved_handlers = dict(_TOOL_HANDLERS)
    _TOOL_SPECS.clear()
    _TOOL_HANDLERS.clear()
    yield
    _TOOL_SPECS.clear()
    _TOOL_HANDLERS.clear()
    _TOOL_SPECS.update(saved_specs)
    _TOOL_HANDLERS.update(saved_handlers)


def test_register_payment_tool_adds_to_registry():
    """Importing and calling register() adds request_payment to the registry."""
    from kaji.tools.payment import register_payment_tool
    register_payment_tool(api_base_url="http://api.test", api_key="tok")
    assert "request_payment" in _TOOL_SPECS
    spec = _TOOL_SPECS["request_payment"]
    assert spec.name == "request_payment"
    assert "amount_cents" in spec.parameters["properties"]
    assert "description" in spec.parameters["properties"]


@pytest.mark.asyncio
async def test_request_payment_returns_checkout_url(monkeypatch):
    """Successful API call returns client_secret."""
    from kaji.tools.payment import register_payment_tool
    register_payment_tool(api_base_url="http://api.test", api_key="tok")

    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {
        "session": {"id": "sess-1", "status": "pending"},
        "client_secret": "pi_secret_abc",
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        ctx = ToolContext(user_id="user-1")
        handler = _TOOL_HANDLERS["request_payment"]
        result = await handler(ctx, {
            "agent_id": "agent-1",
            "amount_cents": 1000,
            "description": "One coffee",
        })

    assert result["client_secret"] == "pi_secret_abc"
    assert result["session_id"] == "sess-1"
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_request_payment_handles_api_error(monkeypatch):
    """Non-2xx from API returns error dict (does not raise)."""
    from kaji.tools.payment import register_payment_tool
    register_payment_tool(api_base_url="http://api.test", api_key="tok")

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "internal server error"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        ctx = ToolContext(user_id="user-1")
        handler = _TOOL_HANDLERS["request_payment"]
        result = await handler(ctx, {
            "agent_id": "agent-1",
            "amount_cents": 500,
            "description": "test",
        })

    assert result["status"] == "error"
    assert "error" in result


@pytest.mark.asyncio
async def test_request_payment_missing_required_args():
    """Missing required args returns error dict."""
    from kaji.tools.payment import register_payment_tool
    register_payment_tool(api_base_url="http://api.test", api_key="tok")

    ctx = ToolContext(user_id="user-1")
    handler = _TOOL_HANDLERS["request_payment"]
    result = await handler(ctx, {"description": "no amount"})

    assert result["status"] == "error"
    assert "amount_cents" in result["error"]


def test_register_twice_raises():
    """Calling register_payment_tool twice raises ValueError."""
    from kaji.tools.payment import register_payment_tool
    register_payment_tool(api_base_url="http://api.test", api_key="tok")
    with pytest.raises(ValueError, match="already registered"):
        register_payment_tool(api_base_url="http://api.test", api_key="tok")
```

- [ ] **Step 2: Run to verify tests fail**

```bash
cd packages/sdk && python -m pytest tests/test_tools_payment.py -v
```

Expected: `ImportError: cannot import name 'register_payment_tool' from 'kaji.tools.payment'`

- [ ] **Step 3: Commit the test file**

```bash
git add packages/sdk/tests/test_tools_payment.py
git commit -m "test(sdk): failing tests for request_payment tool"
```

---

## Task 3: Implement the tool

**Files:**
- Create: `packages/sdk/kaji/tools/payment.py`

- [ ] **Step 1: Write the implementation**

Create `packages/sdk/kaji/tools/payment.py`:

```python
"""request_payment tool for agentpay.

Usage::

    from kaji.tools.payment import register_payment_tool

    register_payment_tool(
        api_base_url=os.environ["AGENTPAY_API_URL"],
        api_key=os.environ["AGENTPAY_API_KEY"],
    )

After calling ``register_payment_tool``, the ``request_payment`` tool is
available in the kaji registry and will be surfaced to any ``AgentRuntime``
configured with it.
"""

from __future__ import annotations

import os
from typing import Any, Dict

import httpx

from kaji.runtime.tools.registry import ToolContext, ToolSpec, register_tool


def register_payment_tool(
    api_base_url: str | None = None,
    api_key: str | None = None,
) -> None:
    """Register the request_payment tool with the kaji registry.

    Args:
        api_base_url: Base URL for @agentpay/api.
                      Defaults to env var ``AGENTPAY_API_URL``.
        api_key:      Bearer token for the API.
                      Defaults to env var ``AGENTPAY_API_KEY``.

    Raises:
        ValueError: If the tool is already registered.
    """
    resolved_url = api_base_url or os.environ.get("AGENTPAY_API_URL", "http://localhost:8090")
    resolved_key = api_key or os.environ.get("AGENTPAY_API_KEY", "")

    spec = ToolSpec(
        name="request_payment",
        description=(
            "Request payment from the customer for a product or service. "
            "Returns a client_secret that can be used to complete payment via Stripe."
        ),
        parameters={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "The agentpay agent ID handling this session.",
                },
                "amount_cents": {
                    "type": "integer",
                    "description": "Amount to charge in cents (e.g. 1000 = $10.00).",
                },
                "description": {
                    "type": "string",
                    "description": "Plain-language description of what is being paid for.",
                },
                "channel": {
                    "type": "string",
                    "description": "Modality: chat, voice, or sms. Defaults to chat.",
                    "enum": ["chat", "voice", "sms"],
                },
            },
            "required": ["agent_id", "amount_cents", "description"],
        },
    )

    @register_tool(spec)
    async def request_payment(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
        # Validate required args
        if "amount_cents" not in args:
            return {"status": "error", "error": "amount_cents is required"}
        if "agent_id" not in args:
            return {"status": "error", "error": "agent_id is required"}
        if "description" not in args:
            return {"status": "error", "error": "description is required"}

        payload = {
            "agent_id": args["agent_id"],
            "amount_cents": int(args["amount_cents"]),
            "description": args["description"],
            "channel": args.get("channel", "chat"),
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{resolved_url.rstrip('/')}/v1/sessions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {resolved_key}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.RequestError as exc:
            return {"status": "error", "error": f"network error: {exc}"}

        if response.status_code not in (200, 201):
            return {
                "status": "error",
                "error": f"API returned {response.status_code}: {response.text}",
            }

        data = response.json()
        return {
            "status": "ok",
            "session_id": data["session"]["id"],
            "client_secret": data["client_secret"],
        }
```

- [ ] **Step 2: Run the tests**

```bash
cd packages/sdk && python -m pytest tests/test_tools_payment.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add packages/sdk/kaji/tools/payment.py
git commit -m "feat(sdk): request_payment agentpay tool"
```

---

## Task 4: Export from public API

**Files:**
- Modify: `packages/sdk/kaji/__init__.py`

- [ ] **Step 1: Check current lazy export map**

```bash
cd packages/sdk && grep -n "register_payment_tool\|kaji.tools" kaji/__init__.py | head -10
```

Expected: no results (not yet exported).

- [ ] **Step 2: Add to lazy export map**

Open `packages/sdk/kaji/__init__.py` and find the `_LAZY_MAP` dict. Add:

```python
"register_payment_tool": "kaji.tools.payment",
```

- [ ] **Step 3: Verify the public import works**

```bash
cd packages/sdk && python -c "import kaji; print(kaji.register_payment_tool)"
```

Expected: `<function register_payment_tool at 0x...>`

- [ ] **Step 4: Run all SDK tests to catch regressions**

```bash
cd packages/sdk && python -m pytest tests/ -v --tb=short
```

Expected: all tests pass (83+ passing).

- [ ] **Step 5: Commit**

```bash
git add packages/sdk/kaji/__init__.py
git commit -m "feat(sdk): export register_payment_tool from public API"
```

---

## Task 5: Integration usage example

- [ ] **Step 1: Verify end-to-end wiring with mock provider**

Run this snippet in a Python shell (no API key or real endpoint needed):

```python
import asyncio
import kaji
from unittest.mock import patch, AsyncMock, MagicMock

# Register the tool pointed at a mock URL
kaji.register_payment_tool(api_base_url="http://localhost:8090", api_key="test-token")

# Confirm it appears in the registry
specs = kaji.list_tool_specs()
names = [s.name for s in specs]
assert "request_payment" in names, f"tool not registered: {names}"
print("request_payment registered:", next(s for s in specs if s.name == "request_payment"))
```

Expected: prints the ToolSpec with `name='request_payment'`.

- [ ] **Step 2: Commit final state**

```bash
git commit --allow-empty -m "chore(sdk): request_payment tool verified end-to-end"
```
