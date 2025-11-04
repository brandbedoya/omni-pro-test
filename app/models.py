import enum


class EmailStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    ERROR = "ERROR"
