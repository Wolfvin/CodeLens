"""Synthetic fixture: a second ``update`` method to force disambiguation.

Without this file, ``edge_resolver`` would pick ``Profile.update`` for any
call to ``update`` because it is the only candidate. With this file,
``edge_resolver`` picks ``Cache.update`` for the call from ``main.py``
since ``cache.py`` sorts before ``models.py`` alphabetically. The hybrid
type resolver must then refine the edge to point to ``Profile.update``
which is the correct target given the ``user.profile.update`` receiver.
"""


class Cache:
    """A cache class with its own ``update`` method."""

    def update(self, key=None, value=None):
        """Update a cache entry. Unrelated to Profile.update."""
        return self
