"""Shared object-level access rules (RBAC at route level is not enough)."""
from app.core.errors import NotFoundError
from app.models.enums import ListingStatus, UserRole
from app.models.listing import Listing
from app.models.user import User

PUBLIC_LISTING_STATUSES = {ListingStatus.ACTIVE, ListingStatus.RESERVED, ListingStatus.SOLD}


def is_owner(user: User, listing: Listing) -> bool:
    return listing.farmer_id == user.id


def assert_can_view_listing(user: User, listing: Listing | None) -> Listing:
    """404 (not 403) for hidden listings so existence is not leaked."""
    if listing is None:
        raise NotFoundError("Listing not found")
    if user.role == UserRole.ADMIN or is_owner(user, listing) or listing.status in PUBLIC_LISTING_STATUSES:
        return listing
    raise NotFoundError("Listing not found")


def assert_owner_listing(user: User, listing: Listing | None, *, allow_admin: bool = False) -> Listing:
    if listing is None:
        raise NotFoundError("Listing not found")
    if is_owner(user, listing) or (allow_admin and user.role == UserRole.ADMIN):
        return listing
    raise NotFoundError("Listing not found")
