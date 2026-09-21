from dataclasses import dataclass

from enum import Enum


class OperationType(Enum):

    PUT = "PUT"

    DELETE = "DELETE"


@dataclass(frozen=True)

class KeyValue:

    key: str

    value: str

    seq: int

    tombstone: bool
