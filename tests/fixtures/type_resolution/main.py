"""Synthetic fixture entry point for hybrid type resolution tests (issue #13).

Imports ``User`` from ``models`` and calls ``user.profile.update()`` so the
type resolver can refine the resulting CALLS edge to ``Profile.update``.
"""

from models import User


def main():
    user = User("alice")
    user.profile.update({"email": "alice@example.com"})
    user.greet()
    return user
