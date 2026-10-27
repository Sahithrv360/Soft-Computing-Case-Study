"""Optional RFID interface; reader and card technologies are unconfirmed."""
from typing import Protocol

class RFIDReader(Protocol):
    def read_identifier(self) -> str | None: ...

class UnconfiguredRFIDReader:
    def read_identifier(self) -> str | None:
        raise NotImplementedError("Confirm reader, card technology, interface and voltage before setup")
