"""Domain and infrastructure errors.

``DataIntegrityError`` and its subclasses are the vehicle for requirement 51: when any
of them is raised during the BUY path, the scanner records the failure in ``audit_logs``
and refuses to create a signal. They are never swallowed silently.
"""

from __future__ import annotations


class EquitySignalError(Exception):
    """Base class. ``code`` is what surfaces in the API error envelope."""

    code = "internal_error"
    http_status = 500

    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "detail": self.detail}}


class DataIntegrityError(EquitySignalError):
    """Data is missing, stale or inconsistent — no new BUY signal may be created."""

    code = "data_integrity"
    http_status = 503


class StaleDataError(DataIntegrityError):
    code = "stale_data"


class InsufficientHistoryError(DataIntegrityError):
    code = "insufficient_history"


class MarketDataUnavailableError(DataIntegrityError):
    code = "market_data_unavailable"


class RegimeUnknownError(DataIntegrityError):
    code = "regime_unknown"


class ProviderError(EquitySignalError):
    code = "provider_error"
    http_status = 502


class NotFoundError(EquitySignalError):
    code = "not_found"
    http_status = 404


class ValidationError(EquitySignalError):
    code = "validation_error"
    http_status = 422


class AuthError(EquitySignalError):
    code = "unauthorized"
    http_status = 401


class DuplicateAlertError(EquitySignalError):
    code = "duplicate_alert"
    http_status = 409
