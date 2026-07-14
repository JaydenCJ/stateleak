"""Innocent bystanders: pure tests with no shared state at all.

They exist so the minimizer has something to eliminate — a real suite is
mostly tests like these, and stateleak must prove they are irrelevant.
"""

import unittest


def unit_price(qty):
    if qty >= 100:
        return 8.0
    if qty >= 10:
        return 9.0
    return 10.0


class PricingTests(unittest.TestCase):
    def test_small_orders_pay_list_price(self):
        self.assertEqual(unit_price(1), 10.0)

    def test_bulk_discount_at_ten_units(self):
        self.assertEqual(unit_price(10), 9.0)

    def test_pallet_discount_at_hundred_units(self):
        self.assertEqual(unit_price(100), 8.0)
