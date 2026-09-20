# Inside /Users/mac/MyworkProjects/agent/tests/test_schemas.py

import sys
import os
from pydantic import ValidationError
import json
import pytest
import copy

# Get the current file's directory (.../tests)
current_dir = os.path.dirname(__file__)
# Go up one level to the project root (.../agent)
project_root = os.path.abspath(os.path.join(current_dir, '..'))
# Add the root to Python's path so it can find 'app'
sys.path.insert(0, project_root)
# Now import your file
from app.schemas.request import *

json_path = os.path.join(project_root, 'contracts', 'ai_request.json')

# ai_request.json is a JSON Schema, not a request payload.
# The actual valid request lives in its "examples" array.
@pytest.fixture
def valid_payload():
    with open(json_path, 'r') as file:
        schema = json.load(file)
    example_payload = schema.get("examples", [])[0]
    return example_payload


def test_valid_request_parses(valid_payload):
    validated_data = AgentRequest(**valid_payload)
    assert validated_data is not None


def test_missing_required_field_fails(valid_payload):
    """Test that deleting a required field triggers a validation error."""
    mutated = copy.deepcopy(valid_payload)
    del mutated["severity"]
    with pytest.raises(ValidationError):
        AgentRequest(**mutated)


def test_missing_network_status_fails(valid_payload):
    """Test that deleting the network_status field triggers a validation error."""
    mutated = copy.deepcopy(valid_payload)
    del mutated["network_status"]
    with pytest.raises(ValidationError):
        AgentRequest(**mutated)


def test_phone_missing_plus_fails(valid_payload):
    """Test that a phone number without a leading '+' fails validation."""
    mutated = copy.deepcopy(valid_payload)
    mutated["devices"][0]["phone"] = "1234567890"
    with pytest.raises(ValidationError):
        AgentRequest(**mutated)


def test_21_devices_fails(valid_payload):
    """Test that having more than 20 devices fails validation."""
    mutated = copy.deepcopy(valid_payload)
    for _ in range(20):
        mutated["devices"].append(copy.deepcopy(mutated["devices"][0]))
    with pytest.raises(ValidationError):
        AgentRequest(**mutated)