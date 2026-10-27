"""Display boundary; terminal output is the currently supported display."""
from typing import Protocol

class Display(Protocol):
    def show(self, message: str) -> None: ...

class TerminalDisplay:
    def show(self, message: str) -> None:
        print(message)

class LCD16x2Placeholder:
    def show(self, message: str) -> None:
        raise NotImplementedError("Confirm LCD controller, interface, pinout and voltage before setup")
