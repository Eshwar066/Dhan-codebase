from enum import Enum


class OrderStatus(Enum):
    CREATED = "CREATED"
    SENT = "SENT"
    ACK = "ACK"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
