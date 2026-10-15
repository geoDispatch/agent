import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import OLLAMA_MODEL, OLLAMA_URL
from app.fallback import fallback
from app.schemas.request import AgentRequest
from app.schemas.response import AgentResponse
from app.validators.semantic import semantic_validator


pytestmark = pytest.mark.anyio
CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
CHAT_URL = f"{OLLAMA_URL}/api/chat"
SYSTEM_PROMPT = (
    "Return exactly one decision for each input device. "
    "Do not duplicate devices. "
    "Do not invent devices. "
    "Do not omit devices. "
    "Each input phone must appear exactly once in decisions. "
    "The number of decisions must equal the number of input devices."
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def run_agent():
    # Import here so application import errors do not stop the rest of the suite.
    from app.agent import run_agent

    return run_agent


@pytest.fixture
def agent_request():
    contract = json.loads((CONTRACTS / "ai_request.json").read_text())
    return AgentRequest.model_validate(contract["examples"][0])


@pytest.fixture
def expected_response(agent_request):
    # The contract example has more decisions than the request has devices;
    # keep only matching phones so the mock passes semantic validation.
    contract = json.loads((CONTRACTS / "ai_response.json").read_text())
    example = contract["examples"][0]
    phones = {device.phone for device in agent_request.devices}
    example["decisions"] = [d for d in example["decisions"] if d["phone"] in phones]
    return AgentResponse.model_validate(example)


def assert_matches_request(response, request):
    assert isinstance(response, AgentResponse)
    assert response.event_id == request.event_id
    assert response.zone == request.zone
    assert len(response.decisions) == len(request.devices)
    assert {d.phone for d in response.decisions} == {d.phone for d in request.devices}
    semantic_validator(request, response)


def chat_response(content):
    return httpx.Response(
        200,
        request=httpx.Request("POST", CHAT_URL),
        json={
            "model": OLLAMA_MODEL,
            "message": {"role": "assistant", "content": content},
            "done": True,
        },
    )


@pytest.fixture
def ollama_post(monkeypatch, expected_response):
    post = AsyncMock(return_value=chat_response(expected_response.model_dump_json()))
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    return post


async def test_run_agent_success(run_agent, agent_request, expected_response, ollama_post):
    response = await run_agent(agent_request)

    assert_matches_request(response, agent_request)
    assert response == expected_response
    assert response != fallback(agent_request)

    # The schema pins the decision count to the number of request devices.
    schema = AgentResponse.model_json_schema()
    schema["properties"]["decisions"]["minItems"] = len(agent_request.devices)
    schema["properties"]["decisions"]["maxItems"] = len(agent_request.devices)
    ollama_post.assert_awaited_once_with(
        CHAT_URL,
        json={
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": agent_request.model_dump_json()},
            ],
            "stream": False,
            "format": schema,
            "options": {"temperature": 0},
        },
    )


async def test_run_agent_invalid_model_json(run_agent, agent_request, ollama_post, capsys):
    ollama_post.return_value = chat_response("not valid JSON")

    response = await run_agent(agent_request)

    assert_matches_request(response, agent_request)
    assert response == fallback(agent_request)
    ollama_post.assert_awaited_once()
    output = capsys.readouterr().out
    assert "AI response validation failed:" in output
    assert "json_invalid" in output


async def test_run_agent_invalid_response_schema(
    run_agent, agent_request, expected_response, ollama_post, capsys
):
    payload = expected_response.model_dump(mode="json")
    payload["decisions"][0]["action"] = "invalid_action"
    ollama_post.return_value = chat_response(json.dumps(payload))

    response = await run_agent(agent_request)

    assert_matches_request(response, agent_request)
    assert response == fallback(agent_request)
    ollama_post.assert_awaited_once()
    output = capsys.readouterr().out
    assert "AI response validation failed:" in output
    assert "decisions.0.action" in output


async def test_run_agent_http_failure(run_agent, agent_request, ollama_post, capsys):
    ollama_post.return_value = httpx.Response(
        500,
        request=httpx.Request("POST", CHAT_URL),
        json={"error": "Ollama failed"},
    )

    response = await run_agent(agent_request)

    assert_matches_request(response, agent_request)
    assert response == fallback(agent_request)
    ollama_post.assert_awaited_once()
    output = capsys.readouterr().out
    assert "Ollama HTTP error:" in output
    assert "500" in output


async def test_run_agent_timeout(run_agent, agent_request, ollama_post, capsys):
    ollama_post.side_effect = httpx.TimeoutException(
        "Ollama timed out", request=httpx.Request("POST", CHAT_URL)
    )

    response = await run_agent(agent_request)

    assert_matches_request(response, agent_request)
    assert response == fallback(agent_request)
    ollama_post.assert_awaited_once()
    assert "Ollama HTTP error: Ollama timed out" in capsys.readouterr().out
