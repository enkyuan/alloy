# Stripe test-mode refund agent

A product-action example, not a chatbot. It wraps an existing Stripe refund
function as a Kaji `Capability`, starts a `Task` with a principal, requires a
risk-based approval, calls Stripe test mode, and records a `stripe/refund`
`ArtifactRef` in task history.

## Run a real test refund

Use a Stripe **test-mode** secret and a refundable test payment intent. This
creates a real Stripe test-mode refund.

```bash
cd examples/refund-agent
python -m venv .venv
. .venv/bin/activate
pip install "kaji>=0.3.0a1,<0.4"
export STRIPE_SECRET_KEY=sk_test_...
export STRIPE_PAYMENT_INTENT=pi_...
export REFUND_AMOUNT_CENTS=500
python refund_agent.py
```

The process asks for explicit approval before it calls Stripe. The example uses
the current alpha's process-bound approval path: approve while the process is
running. It does not claim restartable approval continuation.

## Verify without Stripe

```bash
uv run --project ../../kaji/packages/py --no-sync python smoke.py
```

The smoke uses a local Stripe response stub. It proves the capability request,
canonical approval event, one refund call, artifact projection, and task-history
lookup without network access.

Only installed Kaji package APIs are imported; the example has no Ryo imports.
