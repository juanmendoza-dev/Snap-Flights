"""The shared fixtures live in the repository-root ``conftest.py``.

They were here until unit tests started living beside the code they test (L0 §1, review
C5): a conftest applies to its own directory downwards, so anything under ``pipeline/`` or
``api/`` would have run without the environment isolation and the offline guard.
"""
