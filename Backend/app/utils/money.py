"""Money is integer paise internally; rupees only at the API edge. Never use float for money."""
from decimal import ROUND_HALF_UP, Decimal


def rupees_to_paise(value: Decimal) -> int:
    scaled = value * 100
    if scaled != scaled.to_integral_value():
        raise ValueError("Amount can have at most 2 decimal places")
    return int(scaled)


def paise_to_rupees(paise: int) -> Decimal:
    return (Decimal(paise) / 100).quantize(Decimal("0.01"))


def line_total_paise(quantity_kg: Decimal, unit_price_paise: int) -> int:
    """quantity (kg, up to 3dp) x price per kg (paise), rounded half-up to whole paise."""
    return int((quantity_kg * unit_price_paise).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def fmt_kg(value: Decimal) -> str:
    """Human-friendly quantity: Decimal('200.000') -> '200', Decimal('12.500') -> '12.5' (never scientific notation)."""
    d = Decimal(value).normalize()
    return f"{d:f}" if d == d.to_integral_value() or (isinstance(exp := d.as_tuple().exponent, int) and exp < 0) else f"{d.quantize(Decimal(1)):f}"
