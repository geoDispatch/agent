# Inside /Users/mac/MyworkProjects/agent/tests/test_schemas_response.py

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
from app.schemas.response import *

json_path = os.path.join(project_root, 'contracts', 'ai_response.json')

# ai_response.json is a JSON Schema, not a response payload.
# The actual valid response lives in its "examples" array.
@pytest.fixture
def valid_response_payload():
    with open(json_path, 'r') as file:
        schema = json.load(file)
    example_payload = schema.get("examples", [])[0]
    return example_payload


def test_valid_response_parses(valid_response_payload):
    validated_data = AgentResponse(**valid_response_payload)
    assert validated_data is not None


def test_invalid_action_fails(valid_response_payload):
    """Test that an action outside the allowed enum fails validation."""
    mutated = copy.deepcopy(valid_response_payload)
    mutated["decisions"][0]["action"] = "evacuate"
    with pytest.raises(ValidationError):
        AgentResponse(**mutated)


def test_rescue_priority_out_of_range_fails(valid_response_payload):
    """Test that a rescue_priority above the max of 10 fails validation."""
    mutated = copy.deepcopy(valid_response_payload)
    mutated["decisions"][0]["rescue_priority"] = 11
    with pytest.raises(ValidationError):
        AgentResponse(**mutated)


def test_sms_message_too_long_fails(valid_response_payload):
    """Test that an sms_message longer than 320 characters fails validation."""
    mutated = copy.deepcopy(valid_response_payload)
    mutated["decisions"][0]["sms_message"] = "a" * 321
    with pytest.raises(ValidationError):
        AgentResponse(**mutated)


def test_missing_reasoning_fails(valid_response_payload):
    """Test that deleting the required reasoning field triggers a validation error."""
    mutated = copy.deepcopy(valid_response_payload)
    del mutated["decisions"][0]["reasoning"]
    with pytest.raises(ValidationError):
        AgentResponse(**mutated)


def test_confidence_out_of_range_fails(valid_response_payload):
    """Test that a top-level confidence above the max of 1.0 fails validation."""
    mutated = copy.deepcopy(valid_response_payload)
    mutated["confidence"] = 1.5
    with pytest.raises(ValidationError):
        AgentResponse(**mutated)
