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
    L.SOLD: {L.ACTIVE},  # only via InventoryService.restock_many (refund of a fully sold listing)
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


from app.models.enums import PaymentStatus as P  # noqa: E402

# A payment mirrors ONE provider order. A failed attempt may still be retried by the buyer on the same provider order,
# so FAILED -> SUCCESS is legal; SUCCESS can never go back to FAILED (stale/out-of-order events are ignored).
PAYMENT_TRANSITIONS: dict[P, set[P]] = {
    P.CREATED: {P.PENDING, P.FAILED, P.SUCCESS},
    P.PENDING: {P.SUCCESS, P.FAILED},
    P.FAILED: {P.SUCCESS},
    P.SUCCESS: {P.REFUND_REQUESTED},
    P.REFUND_REQUESTED: {P.REFUNDED, P.SUCCESS},  # SUCCESS again when a refund fails / a partial refund completes
    P.REFUNDED: set(),
}


from app.models.enums import DisputeStatus as D  # noqa: E402

DISPUTE_TRANSITIONS: dict[D, set[D]] = {
    D.OPEN: {D.UNDER_REVIEW, D.EVIDENCE_REQUESTED, D.RESOLVED, D.REFUND_REQUIRED},
    D.UNDER_REVIEW: {D.EVIDENCE_REQUESTED, D.RESOLVED, D.REFUND_REQUIRED},
    D.EVIDENCE_REQUESTED: {D.UNDER_REVIEW, D.RESOLVED, D.REFUND_REQUIRED},
    D.REFUND_REQUIRED: {D.RESOLVED},  # resolved automatically once the refund fully completes
    D.RESOLVED: {D.CLOSED},
    D.CLOSED: set(),
}


from app.models.enums import AnomalyStatus as A  # noqa: E402

ANOMALY_TRANSITIONS: dict[A, set[A]] = {
    A.FLAGGED_FOR_REVIEW: {A.DISMISSED, A.RESOLVED, A.ACTION_REQUESTED},
    A.ACTION_REQUESTED: {A.RESOLVED, A.FLAGGED_FOR_REVIEW},  # back to review if the request is rejected / fails
    A.DISMISSED: set(),
    A.RESOLVED: set(),
}
