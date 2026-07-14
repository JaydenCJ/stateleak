"""The polluter: mutates module state and never resets it.

The missing ``tearDown`` (or an ``addCleanup(inventory.reset)``) is the
entire bug. stateleak's report points here by name.
"""

import unittest

import inventory


class ReceivingTests(unittest.TestCase):
    def test_receiving_adds_stock(self):
        inventory.receive("SKU-1", 5)  # leaks: no reset afterwards
        self.assertEqual(inventory.stock("SKU-1"), 5)

    def test_receiving_rejects_nonpositive_qty(self):
        with self.assertRaises(ValueError):
            inventory.receive("SKU-1", 0)
