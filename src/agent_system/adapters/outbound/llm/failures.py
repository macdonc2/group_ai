"""What to tell a person when a model turn fails.

The full error stays in the logs. This turns the failures a person can act on into a plain
sentence, chosen from the provider's status code and error code and never from its message
text, so nothing the provider wrote is shown to the person.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai.exceptions import ModelHTTPError

OUT_OF_CREDITS = ("The model account is out of credits, so nothing that needs the model will work until "
                  "credits are added. Trying again will not help.")
RATE_LIMITED = "The model provider is rate limiting this account right now. Wait a minute and try again."
KEY_REJECTED = ("The model provider rejected this app's API key. That needs fixing in the app's "
                "settings; trying again will not help.")
PROVIDER_DOWN = "The model provider is having trouble on its side. Please try again in a few minutes."

_NO_CREDIT_CODES = {"insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached",
                    "billing_not_active"}


def _codes(body: Any) -> set[str]:
    """The provider's error `code` and `type`, wherever it nested them."""
    if not isinstance(body, dict):
        return set()
    inner = body.get("error")
    found = {str(source[key]).lower() for source in (body, inner) if isinstance(source, dict)
             for key in ("code", "type") if source.get(key)}
    return found


def failure_message(exc: BaseException) -> str:
    """One sentence for the person about why the turn failed and whether retrying can help."""
    if isinstance(exc, ModelHTTPError):
        if _codes(exc.body) & _NO_CREDIT_CODES:
            return OUT_OF_CREDITS
        if exc.status_code == 429:
            return RATE_LIMITED
        if exc.status_code in (401, 403):
            return KEY_REJECTED
        if exc.status_code >= 500:
            return PROVIDER_DOWN
    return f"Something went wrong on my side ({type(exc).__name__}). Please try again."
