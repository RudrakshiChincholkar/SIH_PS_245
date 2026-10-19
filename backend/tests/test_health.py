from fastapi import status


def test_root_endpoint(client):
    """
    Test that the root endpoint returns 200 and basic API links.
    """
    response = client.get("/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "health_check" in data
    assert "docs_url" in data


def test_api_health_endpoint(client):
    """
    Test the general health endpoint.
    Must return 200 OK and status 'ok' independently of database connectivity.
    """
    response = client.get("/api/health")
    assert response.status_code == status.HTTP_200_OK
    
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "sih-attendance-backend"
    assert "version" in data
    assert "environment" in data
