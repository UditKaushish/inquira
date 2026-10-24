from __future__ import annotations


class ApiError(Exception):
    """An error that is safe to show to the client."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def not_found(what: str = "Resource") -> ApiError:
    return ApiError(404, "not_found", f"{what} not found")


def bad_request(message: str, code: str = "bad_request") -> ApiError:
    return ApiError(400, code, message)
