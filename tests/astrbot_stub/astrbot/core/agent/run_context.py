from typing import Generic, TypeVar

T = TypeVar("T")


class ContextWrapper(Generic[T]):
    def __init__(self, context: T) -> None:
        self.context = context
