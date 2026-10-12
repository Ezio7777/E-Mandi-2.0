"""Controlled vocabularies. Values equal names; stored as native Postgres enums."""
from enum import StrEnum


class UserRole(StrEnum):
    FARMER = "FARMER"
    BUYER = "BUYER"
    ADMIN = "ADMIN"


class AuthProvider(StrEnum):
    LOCAL = "LOCAL"
    GOOGLE = "GOOGLE"
    PHONE = "PHONE"


class OtpPurpose(StrEnum):
    LOGIN = "LOGIN"


class ListingStatus(StrEnum):
    DRAFT = "DRAFT"
    ANALYZING = "ANALYZING"
    ACTIVE = "ACTIVE"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    ARCHIVED = "ARCHIVED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class CropCategory(StrEnum):
    VEGETABLE = "VEGETABLE"
    FRUIT = "FRUIT"
    GRAIN = "GRAIN"
    PULSE = "PULSE"
    SPICE = "SPICE"
    OILSEED = "OILSEED"
    OTHER = "OTHER"


class Grade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class GradingProvider(StrEnum):
    GEMINI = "gemini"
    OPENAI = "openai"
    CACHE = "cache"
    MANUAL = "manual"


class ReviewDecision(StrEnum):
    APPROVED = "APPROVED"
    OVERRIDDEN = "OVERRIDDEN"
    REJECTED = "REJECTED"


class RequirementStatus(StrEnum):
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class MatchStatus(StrEnum):
    SUGGESTED = "SUGGESTED"
    ACCEPTED = "ACCEPTED"
    DISMISSED = "DISMISSED"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAID = "PAID"
    CONFIRMED = "CONFIRMED"
    IN_FULFILLMENT = "IN_FULFILLMENT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DISPUTED = "DISPUTED"
    REFUNDED = "REFUNDED"


class PaymentStatus(StrEnum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUND_REQUESTED = "REFUND_REQUESTED"
    REFUNDED = "REFUNDED"


class RefundStatus(StrEnum):
    REQUESTED = "REQUESTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DisputeStatus(StrEnum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    RESOLVED = "RESOLVED"
    REFUND_REQUIRED = "REFUND_REQUIRED"
    CLOSED = "CLOSED"


class NotificationType(StrEnum):
    NEW_MATCH = "NEW_MATCH"
    NEW_ORDER = "NEW_ORDER"
    PAYMENT_SUCCESSFUL = "PAYMENT_SUCCESSFUL"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    GRADING_COMPLETED = "GRADING_COMPLETED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    DISPUTE_UPDATED = "DISPUTE_UPDATED"
    SYSTEM = "SYSTEM"


class AnomalySeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AnomalyStatus(StrEnum):
    FLAGGED_FOR_REVIEW = "FLAGGED_FOR_REVIEW"
    DISMISSED = "DISMISSED"
    ACTION_REQUESTED = "ACTION_REQUESTED"
    RESOLVED = "RESOLVED"


class PendingActionType(StrEnum):
    BAN_USER = "BAN_USER"
    APPROVE_LOW_CONFIDENCE_GRADE = "APPROVE_LOW_CONFIDENCE_GRADE"
    RESOLVE_SERIOUS_DISPUTE = "RESOLVE_SERIOUS_DISPUTE"


class PendingActionStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class AgentName(StrEnum):
    CROP_GRADING = "CROP_GRADING"
    SMART_PRICING = "SMART_PRICING"
    BUYER_MATCHING = "BUYER_MATCHING"
    VOICE_ASSISTANT = "VOICE_ASSISTANT"
    FRAUD_RISK = "FRAUD_RISK"


class AgentStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
