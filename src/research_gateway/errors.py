from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class GatewayError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 500, **context: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.context = context

    def to_http(self) -> HTTPException:
        return HTTPException(
            status_code=self.status_code,
            detail={
                "code": self.code,
                "message": self.message,
                **self.context,
            },
        )
