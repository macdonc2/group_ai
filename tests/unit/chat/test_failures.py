"""The sentence a person sees when a model turn fails."""

from __future__ import annotations

import pytest
from pydantic_ai.exceptions import ModelHTTPError

from agent_system.adapters.outbound.llm.failures import (
    KEY_REJECTED,
    OUT_OF_CREDITS,
    PROVIDER_DOWN,
    RATE_LIMITED,
    failure_message,
)


def http_error(status: int, body: object = None) -> ModelHTTPError:
    return ModelHTTPError(status_code=status, model_name="m", body=body)


@pytest.mark.parametrize("body", [
    # The shape seen in production on 2026-11-26.
    {"code": "credit_balance_exhausted", "message": "You have no credits remaining.", "type": "insufficient_quota"},
    {"error": {"code": "insufficient_quota", "message": "quota"}},
    {"type": "insufficient_quota"},
])
def test_no_credits_is_named_and_says_retrying_will_not_help(body: dict) -> None:
    message = failure_message(http_error(429, body))
    assert message == OUT_OF_CREDITS
    assert "out of credits" in message


def test_a_plain_429_is_a_rate_limit_not_a_credit_problem() -> None:
    assert failure_message(http_error(429, {"code": "rate_limit_exceeded"})) == RATE_LIMITED
    assert failure_message(http_error(429, "slow down")) == RATE_LIMITED


def test_rejected_key_and_provider_outage() -> None:
    assert failure_message(http_error(401, {"code": "invalid_api_key"})) == KEY_REJECTED
    assert failure_message(http_error(503)) == PROVIDER_DOWN


def test_provider_text_is_never_shown() -> None:
    body = {"code": "insufficient_quota", "message": "SECRET-ORG-NAME see https://example.com/billing"}
    assert "SECRET" not in failure_message(http_error(429, body))
    assert "example.com" not in failure_message(http_error(400, body | {"code": "other"}))


def test_anything_else_keeps_the_generic_message_with_the_error_type() -> None:
    assert failure_message(http_error(400, {"code": "invalid_request"})).startswith("Something went wrong on my side (ModelHTTPError)")
    assert "(KeyError)" in failure_message(KeyError("x"))
