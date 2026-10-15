from pydantic import ValidationError
import httpx

from app.config import OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT
from app.schemas.request import AgentRequest
from app.schemas.response import AgentResponse
from app.validators.semantic import semantic_validator
from app.fallback import fallback


def Generate_messages(request_json: str, device_count: int) -> dict:
    schema = AgentResponse.model_json_schema()
    schema["properties"]["decisions"]["minItems"] = device_count
    schema["properties"]["decisions"]["maxItems"] = device_count

    messages = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return exactly one decision for each input device. "
                    "Do not duplicate devices. "
                    "Do not invent devices. "
                    "Do not omit devices. "
                    "Each input phone must appear exactly once in decisions. "
                    "The number of decisions must equal the number of input devices."
                ),
            },
            {
                "role": "user",
                "content": request_json,
            },
        ],
        "stream": False,
        "format": schema,
        "options": {
            "temperature": 0
        },
    }
    return messages

async def run_ollama(messages: dict) -> dict:
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        response = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json=messages
        )
        response.raise_for_status()
        return response.json()


async def run_agent(request: AgentRequest) -> AgentResponse:
    request_json = request.model_dump_json()
    msg = Generate_messages(request_json,len(request.devices))

    try:
        response = await run_ollama(msg)
        content = response["message"]["content"]
        agent_response = AgentResponse.model_validate_json(content)

        print("request devices:", len(request.devices))
        print("ai decisions:", len(agent_response.decisions))
        print("request phones:", [d.phone for d in request.devices])
        print("AI phones:", [d.phone for d in agent_response.decisions])

        semantic_validator(
            request,
            agent_response
        )
        return agent_response
    except httpx.HTTPError as error:
        print(f"Ollama HTTP error: {error}")
    except (ValidationError, ValueError, KeyError, TypeError) as error:
        print(f"AI response validation failed: {error}")
    fallback_response = fallback(request)
    semantic_validator(
        request,
        fallback_response
    )
    return fallback_response