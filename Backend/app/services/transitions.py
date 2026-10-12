"""Single source of truth for state machines. Services call assert_transition(); routes never mutate status."""
from enum import Enum

from app.core.errors import InvalidTransitionError
from app.models.enums import ListingStatus as L
from app.models.enums import OrderStatus as O

LISTING_TRANSITIONS: dict[L, set[L]] = {
    L.DRAFT: {L.ANALYZING, L.ARCHIVED},
    L.ANALYZING: {L.ACTIVE, L.REVIEW_REQUIRED},
    L.REVIEW_REQUIRED: {L.ACTIVE, L.ARCHIVED, L.ANALYZING},
    L.ACTIVE: {L.RESERVED, L.SOLD, L.ARCHIVED},
    L.RESERVED: {L.ACTIVE, L.SOLD},
    L.SOLD: set(),
    L.ARCHIVED: {L.DRAFT},
}

ORDER_TRANSITIONS: dict[O, set[O]] = {
    O.PENDING: {O.RESERVED, O.CANCELLED},
    O.RESERVED: {O.PAYMENT_PENDING, O.CANCELLED},
    O.PAYMENT_PENDING: {O.PAID, O.CANCELLED},
    O.PAID: {O.CONFIRMED, O.DISPUTED, O.CANCELLED},
    O.CONFIRMED: {O.IN_FULFILLMENT, O.DISPUTED},
    O.IN_FULFILLMENT: {O.COMPLETED, O.DISPUTED},
    O.COMPLETED: {O.DISPUTED},
    O.DISPUTED: {O.REFUNDED, O.COMPLETED},
    O.CANCELLED: {O.REFUNDED},  # only meaningful when the order had been PAID (checked by OrderService)
    O.REFUNDED: set(),
}


def assert_transition(table: dict, current: Enum, target: Enum) -> None:
    if target not in table.get(current, set()):
        raise InvalidTransitionError(f"Cannot move from {current.value} to {target.value}")
