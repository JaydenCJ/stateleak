"""The victim: assumes the warehouse starts empty.

Perfectly correct in isolation and in alphabetical order (audit < receiving),
so it passes every normal run — until a parallel or shuffled run schedules
``test_receiving`` first.
"""

import unittest

import inventory


class AuditTests(unittest.TestCase):
    def test_warehouse_starts_empty(self):
        self.assertEqual(inventory.total_units(), 0)

    def test_unknown_sku_has_zero_stock(self):
        self.assertEqual(inventory.stock("SKU-404"), 0)
