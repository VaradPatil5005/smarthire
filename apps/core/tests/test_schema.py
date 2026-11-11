"""The published API reference must describe real routes and useful JSON bodies."""

from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.validation import validate_schema

from apps.core.schema import ApprovedSchemaGenerator


def _operations(schema):
    methods = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
    return {
        (path, method)
        for path, item in schema["paths"].items()
        for method in item
        if method in methods
    }


def test_approved_schema_has_exact_live_route_and_method_set():
    approved = ApprovedSchemaGenerator().get_schema(public=True)
    discovered = SchemaGenerator().get_schema(public=True)
    assert _operations(approved) == _operations(discovered)
    validate_schema(approved)


def test_approved_schema_contains_request_and_response_shapes():
    schema = ApprovedSchemaGenerator().get_schema(public=True)
    operation = schema["paths"]["/api/profiles/"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"]
    assert operation["responses"]["201"]["content"]["application/json"]["schema"]
    results = schema["paths"]["/api/runs/{id}/results/"]["get"]
    assert results["responses"]["200"]["content"]["application/json"]["schema"]


def test_schema_response_is_independent_between_calls():
    generator = ApprovedSchemaGenerator()
    first = generator.get_schema(public=True)
    first["info"]["title"] = "Modified by a consumer"
    assert generator.get_schema(public=True)["info"]["title"] == "SmartHireAI API"


def test_public_schema_endpoint_uses_approved_contract(client):
    response = client.get("/api/schema/", HTTP_ACCEPT="application/vnd.oai.openapi+json")
    assert response.status_code == 200
    published = response.json()
    assert published == ApprovedSchemaGenerator().get_schema(public=True)
