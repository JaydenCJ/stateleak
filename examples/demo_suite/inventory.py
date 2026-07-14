"""A tiny inventory module with a module-level cache.

This is the classic shape of a test-order bug: convenient shared state at
module scope, mutated by production code, and one test suite that forgets
to reset it. Nothing here is contrived — swap ``_STOCK`` for a Django
settings override, a singleton connection pool, or ``os.environ`` and the
failure mode is identical.
"""

_STOCK = {}


def stock(sku):
    """Units on hand for ``sku`` (0 when unknown)."""
    return _STOCK.get(sku, 0)


def receive(sku, qty):
    """Record ``qty`` incoming units of ``sku``."""
    if qty <= 0:
        raise ValueError("qty must be positive")
    _STOCK[sku] = _STOCK.get(sku, 0) + qty


def total_units():
    """Total units across every SKU in the warehouse."""
    return sum(_STOCK.values())


def reset():
    """Clear the warehouse. Tests that mutate stock should call this."""
    _STOCK.clear()
