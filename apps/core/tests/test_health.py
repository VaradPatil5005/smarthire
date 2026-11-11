import pytest
from django.db import connection


def test_healthz_returns_ok(client):
    response = client.get("/healthz/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_rejects_writes(client):
    assert client.post("/healthz/").status_code == 405


@pytest.mark.django_db
def test_database_reachable():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)
