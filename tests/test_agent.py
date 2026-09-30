import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from app.config import OLLAMA_MODEL, OLLAMA_URL
from app.schemas.request import AgentRequest
from app.schemas.response import AgentResponse


pytestmark = pytest.mark.anyio
CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
CHAT_URL = f"{OLLAMA_URL}/api/chat"


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
def expected_response():
    contract = json.loads((CONTRACTS / "ai_response.json").read_text())
    return AgentResponse.model_validate(contract["examples"][0])


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

    assert isinstance(response, AgentResponse)
    assert response.event_id == agent_request.event_id
    assert response.zone == expected_response.zone
    assert response.decisions[0] == expected_response.decisions[0]
    assert response.decisions[0].phone == agent_request.devices[0].phone
    ollama_post.assert_awaited_once_with(
        CHAT_URL,
        json={
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": agent_request.model_dump_json()}],
            "stream": False,
        },
    )


async def test_run_agent_invalid_model_json(run_agent, agent_request, ollama_post):
    ollama_post.return_value = chat_response("not valid JSON")

    with pytest.raises((json.JSONDecodeError, ValidationError)) as error:
        await run_agent(agent_request)

    # Both json.loads and Pydantic JSON parsing are valid parsing approaches.
    if isinstance(error.value, ValidationError):
        assert any(detail["type"] == "json_invalid" for detail in error.value.errors())
    ollama_post.assert_awaited_once()


async def test_run_agent_invalid_response_schema(
    run_agent, agent_request, expected_response, ollama_post
):
    payload = expected_response.model_dump(mode="json")
    payload["decisions"][0]["action"] = "invalid_action"
    ollama_post.return_value = chat_response(json.dumps(payload))

    with pytest.raises(ValidationError) as error:
        await run_agent(agent_request)

    assert any(
        detail["loc"] == ("decisions", 0, "action") and detail["type"] == "enum"
        for detail in error.value.errors()
    )
    ollama_post.assert_awaited_once()


async def test_run_agent_http_failure(run_agent, agent_request, ollama_post, capsys):
    ollama_post.return_value = httpx.Response(
        500,
        request=httpx.Request("POST", CHAT_URL),
        json={"error": "Ollama failed"},
    )

    # The current handler prints HTTP errors and implicitly returns None.
    assert await run_agent(agent_request) is None
    ollama_post.assert_awaited_once()
    output = capsys.readouterr().out
    assert "HTTP error occurred:" in output
    assert "500" in output


async def test_run_agent_timeout(run_agent, agent_request, ollama_post, capsys):
    ollama_post.side_effect = httpx.TimeoutException(
        "Ollama timed out", request=httpx.Request("POST", CHAT_URL)
    )

    assert await run_agent(agent_request) is None
    ollama_post.assert_awaited_once()
    assert "HTTP error occurred: Ollama timed out" in capsys.readouterr().out
