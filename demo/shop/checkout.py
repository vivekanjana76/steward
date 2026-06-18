"""Checkout math for the demo shop — with one intentional, reproducible bug."""


def apply_discount(subtotal: float, percent: float) -> float:
    # BUG: a discount should REDUCE the subtotal, but this adds it instead.
    return subtotal + subtotal * (percent / 100.0)


def order_total(subtotal: float, discount_percent: float, shipping: float) -> float:
    """Total for an order: discounted subtotal plus shipping."""
    return apply_discount(subtotal, discount_percent) + shipping
