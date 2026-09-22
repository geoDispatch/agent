import os
import json
import sys
from fastapi import APIRouter
from app.schemas.request import AgentRequest
from app.schemas.response import AgentResponse

# Get the directory of the current file (app/routers)
current_dir = os.path.dirname(os.path.abspath(__file__))

# Go up TWO levels to reach the project root (.../agent)
project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))

# Add to sys.path if you still need it
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Construct the correct path to the contracts folder
json_path = os.path.join(project_root, 'contracts', 'ai_response.json')

#  Load the JSON and initialize the mock response
with open(json_path, 'r') as file:
    schema: dict = json.load(file)

MOCK_RESPONSE = AgentResponse(**schema["examples"][0])

# Define the router
router = APIRouter()

@router.post("/decide", response_model=AgentResponse)
async def decide(request: AgentRequest) -> AgentResponse:
    return MOCK_RESPONSE