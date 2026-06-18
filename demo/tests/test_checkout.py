"""Tests for the demo shop. ``test_discount_reduces_total`` fails on the bug."""

import unittest

from shop.checkout import apply_discount, order_total


class CheckoutTests(unittest.TestCase):
    def test_discount_reduces_total(self) -> None:
        # A 10% discount on 100 should yield 90, not 110.
        self.assertEqual(apply_discount(100.0, 10.0), 90.0)

    def test_order_total_includes_shipping(self) -> None:
        self.assertEqual(order_total(100.0, 10.0, 5.0), 95.0)


if __name__ == "__main__":
    unittest.main()
