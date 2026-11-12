class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        *,
        events: list[dict] | None = None,
        reset_required: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.events = events or []
        self.reset_required = reset_required

    def body(self) -> dict:
        return {
            "error": {"code": self.code, "message": self.message},
            "events": self.events,
            "reset_required": self.reset_required,
        }
