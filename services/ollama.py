"""Ollama bridge for the GeoDispatch triage agent.

One public function, ``call_agent``: it turns a single validated ``AgentRequest``
(one zone batch) into a validated ``AgentResponse`` by talking to the locally
built ``geodispatch-*`` models via the ``ollama`` library.

Two deliberate design choices baked in here:

* **No system message.** Each ``geodispatch-{earthquake,flood,heatwave}`` model
  carries its full SYSTEM prompt inside its Modelfile (output format, the
  DeviceDecision schema, and the triage rules). Sending our own system message
  would fight the baked-in one — same reasoning as the test_quality.py fix — so
  we send ONLY the user turn produced by the prompt builder.
* **One chat call per device, dispatched concurrently.** The Modelfiles say
  "You receive one TriagedDevice per decision", and the earlier manual tests
  confirmed the models behave best one device at a time. The prompt builders
  serialize a whole ``AgentRequest``, so for each device we build a single-device
  sub-request and run the builder on that — the model then sees exactly one
  device block. All of a batch's per-device calls are fired at once via
  ``asyncio.gather`` over ``ollama.AsyncClient`` instead of a serial loop, so
  wall-clock latency is bounded by the slowest device rather than their sum
  (subject to Ollama's own per-model request queue).
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import ollama
from pydantic import ValidationError

from models.schemas import AgentRequest, AgentResponse, DeviceDecision
from prompts import earthquake as _earthquake
from prompts import flood as _flood
from prompts import heatwave as _heatwave

# disaster_type -> built model name (confirmed via `ollama list`; the bare name
# resolves to the ":latest" tag).
_MODEL_BY_DISASTER = {
    "earthquake": "geodispatch-earthquake",
    "flood": "geodispatch-flood",
    "heatwave": "geodispatch-heatwave",
}

# disaster_type -> the module's build_prompt(request) -> str.
_PROMPT_BUILDER_BY_DISASTER = {
    "earthquake": _earthquake.build_prompt,
    "flood": _flood.build_prompt,
    "heatwave": _heatwave.build_prompt,
}

# Appended to the user turn on the single retry after a bad response.
_RETRY_REMINDER = "\n\nReminder: respond with ONLY the JSON object, no prose"

_RESCUE_ACTIONS = ("rescue_flag", "both")
_SMS_ACTIONS = ("sms", "both")


def _ollama_timeout() -> httpx.Timeout:
    """Timeout for every Ollama HTTP call — the missing guard against a HANG.

    ``ollama.AsyncClient()`` defaults to ``timeout=None`` (httpx reads that as
    *no* timeout), so a model that connects but never finishes generating would
    hang ``/decide`` forever. We split the budget:

    * **connect** short (default 5 s) — if Ollama is down / restarting, the call
      fails fast with a ConnectError instead of blocking, and the request
      surfaces as a clean 500.
    * **read** generous (default 240 s) — a cold model load plus generation can
      legitimately take ~110 s (see docs/README "Latency"), so the read budget
      must clear the slowest honest single-device call with headroom, or we'd
      kill real work.

    Both are overridable via env (``GEODISPATCH_OLLAMA_CONNECT_TIMEOUT`` /
    ``GEODISPATCH_OLLAMA_READ_TIMEOUT``) so tests can force a fast timeout and
    ops can tune per box without a code change.
    """
    connect = float(os.getenv("GEODISPATCH_OLLAMA_CONNECT_TIMEOUT", "5"))
    read = float(os.getenv("GEODISPATCH_OLLAMA_READ_TIMEOUT", "240"))
    return httpx.Timeout(connect=connect, read=read, write=10.0, pool=connect)


class AgentError(RuntimeError):
    """Raised when model output cannot be turned into a valid AgentResponse."""


async def _decide_device(
    client: ollama.AsyncClient, model: str, base_user_msg: str, phone: str
) -> DeviceDecision:
    """Run one device through the model, with a single retry on bad output.

    Retries exactly once (with an appended reminder) if the response fails JSON
    parsing OR Pydantic validation, then raises AgentError — never silently
    dropping the device or swallowing the error. The two attempts for one device
    are sequential (the retry depends on the first failure), but this coroutine
    is run concurrently across devices by ``call_agent``.
    """
    user_msg = base_user_msg
    last_error: str | None = None

    for _attempt in (1, 2):
        try:
            response = await client.chat(
                model=model,
                # No system message on purpose — the Modelfile's SYSTEM covers it.
                messages=[{"role": "user", "content": user_msg}],
                format="json",  # constrain the decoder to emit valid JSON
            )
        except (httpx.HTTPError, ollama.ResponseError, ConnectionError, TimeoutError) as exc:
            # Transport / server-side failure. Note ollama re-wraps a refused
            # connection as a *builtin* ConnectionError (not httpx.ConnectError),
            # so we catch that too; timeouts arrive as httpx.TimeoutException
            # (an httpx.HTTPError). Retrying the identical call against a dead or
            # hung server only doubles the wait, so we fail fast here; call_agent
            # propagates it and the route turns it into a clean 500 (the app
            # stays up for the next request).
            raise AgentError(
                f"Ollama call failed for device {phone} on model {model!r}: {exc!r}"
            ) from exc
        content = response["message"]["content"]

        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            last_error = f"JSON parse error: {exc}"
            user_msg = base_user_msg + _RETRY_REMINDER
            continue

        try:
            return DeviceDecision.model_validate(data)
        except ValidationError as exc:
            last_error = f"schema validation error: {exc}"
            user_msg = base_user_msg + _RETRY_REMINDER
            continue

    raise AgentError(
        f"model {model!r} failed to return a valid DeviceDecision for device "
        f"{phone} after 2 attempts: {last_error}"
    )


async def call_agent(request: AgentRequest) -> AgentResponse:
    """Triage one zone batch: one DeviceDecision per device, run concurrently."""
    disaster = request.disaster_type
    try:
        model = _MODEL_BY_DISASTER[disaster]
        build_prompt = _PROMPT_BUILDER_BY_DISASTER[disaster]
    except KeyError:  # pragma: no cover - Literal type already constrains this
        raise AgentError(f"unsupported disaster_type {disaster!r}") from None

    async def _one(device) -> DeviceDecision:
        # Single-device sub-request so the builder emits exactly one device block.
        single_request = request.model_copy(update={"devices": [device]})
        base_user_msg = build_prompt(single_request)
        return await _decide_device(client, model, base_user_msg, device.phone)

    # Fire every device's call at once and await them together. gather keeps the
    # order of the coroutines it is given, so results[i] lines up with
    # request.devices[i] — the ordered reconciliation below still holds.
    async with ollama.AsyncClient(timeout=_ollama_timeout()) as client:
        results = await asyncio.gather(
            *(_one(device) for device in request.devices),
            return_exceptions=True,
        )

    # Raise the FIRST failure in device order — matching the old serial loop,
    # which stopped at the first device that failed rather than the first to
    # finish. (gather with return_exceptions keeps every sibling running, so a
    # later device's error never pre-empts an earlier one.)
    for res in results:
        if isinstance(res, BaseException):
            raise res
    decisions: list[DeviceDecision] = list(results)  # type: ignore[arg-type]

    # Reconcile: every request phone must have its decision, same order, no
    # extras. A direct ordered compare catches missing, unexpected, and reorders.
    expected = [d.phone for d in request.devices]
    got = [d.phone for d in decisions]
    if got != expected:
        missing = [p for p in expected if p not in got]
        unexpected = [p for p in got if p not in expected]
        raise AgentError(
            "device/decision phone mismatch: "
            f"expected {expected}, got {got}"
            + (f"; missing {missing}" if missing else "")
            + (f"; unexpected {unexpected}" if unexpected else "")
        )

    # request_qos: ask for a QoS boost only when rescue is needed AND QoS is off.
    any_rescue = any(d.action in _RESCUE_ACTIONS for d in decisions)
    request_qos = any_rescue and request.network_status.qos_status == "inactive"

    confidence = round(sum(d.confidence for d in decisions) / len(decisions), 4)

    # Government-facing one-liner: counts only, no phone numbers / PII.
    total = len(decisions)
    flagged = sum(1 for d in decisions if d.action in _RESCUE_ACTIONS)
    sms_sent = sum(1 for d in decisions if d.action in _SMS_ACTIONS)
    gov_narrative = (
        f"{flagged} of {total} devices in the {request.zone} zone flagged for "
        f"rescue; SMS dispatched to {sms_sent}."
    )

    return AgentResponse(
        event_id=request.event_id,
        zone=request.zone,
        decisions=decisions,
        gov_narrative=gov_narrative,
        request_qos=request_qos,
        confidence=confidence,
    )
