"""Verify that a Cursor API key authenticates successfully."""

from __future__ import annotations

from dataclasses import dataclass, field

from cursor_sdk import (
    AuthenticationError,
    ConfigurationError,
    Cursor,
    CursorAgentError,
    NetworkError,
    RateLimitError,
)
from cursor_sdk.types import SDKModel, SDKUser


@dataclass
class VerifyKeyResult:
    ok: bool
    detail: str
    user: SDKUser | None = None
    models: list[SDKModel] = field(default_factory=list)

    def to_text(
        self,
        *,
        show_models: bool = False,
        diagnostics: list[str] | None = None,
    ) -> str:
        lines = ["FTSE 100 Value Investor — Cursor API key check", "=" * 48, ""]
        if diagnostics:
            lines.append("Environment:")
            lines.extend(diagnostics)
            lines.append("")
        if self.ok and self.user is not None:
            name = " ".join(
                part for part in (self.user.user_first_name, self.user.user_last_name) if part
            ).strip()
            lines.append("✓ Authentication succeeded")
            lines.append(f"  Key name: {self.user.api_key_name or '(unnamed)'}")
            if self.user.user_email:
                lines.append(f"  Account:  {self.user.user_email}")
            if name:
                lines.append(f"  Name:     {name}")
            if self.user.created_at:
                lines.append(f"  Created:  {self.user.created_at}")
            if show_models:
                lines.append("")
                if self.models:
                    lines.append(f"Available models ({len(self.models)}):")
                    for model in self.models:
                        lines.append(f"  • {model.id}")
                else:
                    lines.append("No models returned for this account.")
            lines.append("")
            lines.append("Key is valid for deep analysis and research agents.")
        else:
            lines.append(f"✗ {self.detail}")
            lines.append("")
            lines.append(
                "Fix: set CURSOR_API_KEY_V2 or CURSOR_API_KEY to a User API key from "
                "https://cursor.com/dashboard/api-keys "
                "(Team Admin keys are not supported by the SDK) or pass --api-key."
            )
        return "\n".join(lines)


def verify_cursor_api_key(
    api_key: str | None,
    *,
    list_models: bool = False,
) -> VerifyKeyResult:
    """Call Cursor.me (and optionally models.list) to validate the API key."""
    key = (api_key or "").strip()
    if not key:
        return VerifyKeyResult(
            ok=False,
            detail="CURSOR_API_KEY_V2 and CURSOR_API_KEY are not set",
        )

    try:
        user = Cursor.me(api_key=key)
    except AuthenticationError as err:
        return VerifyKeyResult(ok=False, detail=f"Authentication failed: {err}")
    except ConfigurationError as err:
        return VerifyKeyResult(ok=False, detail=f"Invalid key or configuration: {err}")
    except RateLimitError as err:
        return VerifyKeyResult(ok=False, detail=f"Rate limited while verifying key: {err}")
    except NetworkError as err:
        return VerifyKeyResult(ok=False, detail=f"Network error while verifying key: {err}")
    except CursorAgentError as err:
        return VerifyKeyResult(ok=False, detail=f"Cursor API error: {err}")

    models: list[SDKModel] = []
    if list_models:
        try:
            models = list(Cursor.models.list(api_key=key))
        except CursorAgentError as err:
            return VerifyKeyResult(
                ok=False,
                detail=f"Authenticated, but listing models failed: {err}",
                user=user,
            )

    return VerifyKeyResult(
        ok=True,
        detail="ok",
        user=user,
        models=models,
    )
