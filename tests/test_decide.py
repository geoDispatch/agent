# Inside /Users/mac/MyworkProjects/agent/tests/test_decide.py

import sys
import os
import json
import pytest
from fastapi.testclient import TestClient

# Get the current file's directory (.../tests)
current_dir = os.path.dirname(__file__)
# Go up one level to the project root (.../agent)
project_root = os.path.abspath(os.path.join(current_dir, '..'))
# Add the root to Python's path so it can find 'app'
sys.path.insert(0, project_root)
# Now import your files
from app.main import app
from app.schemas.response import AgentResponse

json_path = os.path.join(project_root, 'contracts', 'ai_request.json')

# ai_request.json is a JSON Schema, not a request payload.
# The actual valid request lives in its "examples" array.
@pytest.fixture
def valid_request_payload():
    with open(json_path, 'r') as file:
        schema = json.load(file)
    example_payload = schema.get("examples", [])[0]
    return example_payload


def test_decide_returns_200_with_valid_response(valid_request_payload):
    client = TestClient(app)
    response = client.post("/decide", json=valid_request_payload)
    assert response.status_code == 200
    AgentResponse(**response.json())
    assert response.json()["event_id"] == "EQ-2024-001"


def test_decide_returns_422_on_invalid_request():
    client = TestClient(app)
    response = client.post("/decide", json={})
    assert response.status_code == 422
