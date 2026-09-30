from app.config import OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT
from app.schemas.request import AgentRequest
from app.schemas.response import AgentResponse
import httpx

# Build the chat request payload from the serialized request.
def get_messages(request_json: str) -> dict:
    messages = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "user",
                "content": request_json,
            }
        ],
        "stream": False,
    }
    return messages

# Send the payload to Ollama and return its JSON response.
async def run_ollama(messages: dict) -> dict:
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        response = await client.post(f"{OLLAMA_URL}/api/chat", json=messages)
        response.raise_for_status()
        return response.json()

# Serialize the request, call Ollama, and validate its content while logging HTTP errors.
async def run_agent(request: AgentRequest) -> AgentResponse:
    request_json : str= request.model_dump_json()
    msg = get_messages(request_json)

    try:
        response = await run_ollama(msg)
        content = response["message"]["content"]
        return AgentResponse.model_validate_json(content)
    except httpx.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")  # e.g., 404 Client Error
