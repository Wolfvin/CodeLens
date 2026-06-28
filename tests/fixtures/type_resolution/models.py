"""Synthetic fixture for hybrid type resolution tests (issue #13).

Defines:
  * ``Profile`` class with an ``update`` method.
  * ``User`` class with a ``profile: Profile`` annotated attribute.

This file is imported by ``main.py`` so the type resolver can refine
``user.profile.update()`` into a CALLS edge whose ``resolved_type`` is
``models.Profile``.
"""


class Profile:
    """Profile model with an update method."""

    def update(self, data=None):
        """Update the profile with new data."""
        self._data = data
        return self


class User:
    """User model whose ``profile`` attribute is a Profile instance."""

    def __init__(self, name):
        self.name = name
        self.profile: Profile = Profile()

    def greet(self):
        """Return a greeting."""
        return "Hello, " + self.name
