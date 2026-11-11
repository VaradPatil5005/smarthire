"""The base every factory inherits.

Conventions for a new factory:

- Synthetic data only (CLAUDE.md section 7). Build identities from `factory.Sequence`, so they are
  unique and plainly fictional, and use the reserved `example.test` domain for email addresses.
- Name it `<Model>Factory`, put it in the module for its app, and export it from `__init__.py`.
- Add a smoke test to tests/integration/test_factories.py.
- A tenant-owned model takes its organisation as a required SubFactory. Never default to a shared
  organisation: two factories that silently agree on a tenant would hide isolation bugs.
"""

from factory.django import DjangoModelFactory


class BaseFactory(DjangoModelFactory):
    class Meta:
        abstract = True
        # Post-generation hooks save explicitly. The implicit extra save is deprecated upstream.
        skip_postgeneration_save = True
