"""Publish the reviewed API contract in both Swagger and the schema download.

Most endpoints deliberately use small APIViews instead of ModelViewSets. Automatic serializer
introspection cannot describe their envelopes, status codes and binary responses accurately.
The authored contract is the source of truth; tests pin it to the actual route/method set.
"""

from pathlib import Path

import yaml
from django.conf import settings
from drf_spectacular.generators import SchemaGenerator


class ApprovedSchemaGenerator(SchemaGenerator):
    def get_schema(self, request=None, public=False):
        path = Path(settings.BASE_DIR) / "docs" / "contracts" / "openapi.yaml"
        with path.open(encoding="utf-8") as contract:
            # Load per call: consumers and format renderers cannot mutate shared schema state.
            return yaml.safe_load(contract)
