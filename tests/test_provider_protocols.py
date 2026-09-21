from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError

from backend.config import Settings
from backend.models import resolve_model, resolve_model_settings


async def _echo(value: str) -> str:
    return f"echo:{value}"


def _chat_response(*, tool_call: bool) -> dict[str, Any]:
    if tool_call:
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "_echo", "arguments": '{"value":"ping"}'},
                }
            ],
        }
        finish_reason = "tool_calls"
    else:
        message = {"role": "assistant", "content": "done"}
        finish_reason = "stop"
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": "exact-model-id",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }


def _responses_response(*, tool_call: bool) -> dict[str, Any]:
    if tool_call:
        output = [
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "_echo",
                "arguments": '{"value":"ping"}',
                "status": "completed",
            }
        ]
    else:
        output = [
            {
                "type": "message",
                "id": "msg_1",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "done",
                        "annotations": [],
                        "logprobs": [],
                    }
                ],
            }
        ]
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "background": False,
        "completed_at": 1,
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "max_output_tokens": None,
        "max_tool_calls": None,
        "model": "exact-model-id",
        "output": output,
        "parallel_tool_calls": True,
        "previous_response_id": None,
        "prompt_cache_key": None,
        "prompt_cache_retention": None,
        "reasoning": {"effort": None, "summary": None},
        "safety_identifier": None,
        "service_tier": "default",
        "store": False,
        "temperature": None,
        "text": {"format": {"type": "text"}, "verbosity": "medium"},
        "tool_choice": "auto",
        "tools": [],
        "top_logprobs": 0,
        "top_p": None,
        "truncation": "disabled",
        "usage": {
            "input_tokens": 10,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 3,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 13,
        },
        "user": None,
        "metadata": {},
    }


@pytest.mark.asyncio
async def test_cpa_chat_tool_result_round_trip_uses_chat_wire_format() -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=_chat_response(tool_call=len(requests) == 1))

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    settings = Settings(
        _env_file=None,
        cpa_chat_base_url="https://cpa.example.test/v1",
        cpa_api_key="test-key",
    )
    model = resolve_model("cpa-chat/exact-model-id", settings, http_client=client)

    result = await Agent(model, tools=[_echo]).run("go")

    assert result.output == "done"
    assert len(requests) == 2
    assert requests[1]["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "echo:ping",
    }
    assert result.usage.tool_calls == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_cpa_responses_tool_result_round_trip_uses_responses_wire_format() -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=_responses_response(tool_call=len(requests) == 1))

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    settings = Settings(
        _env_file=None,
        cpa_responses_base_url="https://cpa.example.test/v1",
        cpa_api_key="test-key",
    )
    model = resolve_model("cpa-responses/exact-model-id", settings, http_client=client)

    result = await Agent(model, tools=[_echo]).run("go")

    assert result.output == "done"
    assert len(requests) == 2
    assert requests[1]["input"][-1] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "echo:ping",
    }
    assert result.usage.tool_calls == 1
    await client.aclose()


def _anthropic_response(*, tool_call: bool) -> dict[str, Any]:
    content: list[dict[str, Any]]
    if tool_call:
        content = [
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "_echo",
                "input": {"value": "ping"},
            }
        ]
        stop_reason = "tool_use"
    else:
        content = [{"type": "text", "text": "done"}]
        stop_reason = "end_turn"
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "exact-model-id",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 3},
    }


@pytest.mark.asyncio
async def test_go_messages_headers_session_and_tool_result_round_trip() -> None:
    requests: list[tuple[httpx2.Request, dict[str, Any]]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append((request, json.loads(request.content)))
        return httpx2.Response(200, json=_anthropic_response(tool_call=len(requests) == 1))

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    settings = Settings(_env_file=None, opencode_go_api_key="test-key")
    model = resolve_model(
        "go-messages/exact-model-id",
        settings,
        session_id="stable-session-id",
        http_client=client,
    )

    result = await Agent(
        model,
        model_settings=resolve_model_settings("go-messages/exact-model-id"),
        tools=[_echo],
    ).run("go")

    assert result.output == "done"
    assert len(requests) == 2
    first_request, _ = requests[0]
    assert str(first_request.url).startswith("https://opencode.ai/zen/go/v1/messages")
    assert first_request.headers["x-opencode-session"] == "stable-session-id"
    assert first_request.headers["user-agent"] == "ctf-agent/0.1"
    assert first_request.headers["anthropic-version"] == "2023-06-01"
    _, second_body = requests[1]
    tool_result = second_body["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "toolu_1"
    assert tool_result["content"][0]["text"] == "echo:ping"
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "response_factory", "expected_path"),
    [
        ("go-chat", _chat_response, "/zen/go/v1/chat/completions"),
        ("go-responses", _responses_response, "/zen/go/v1/responses"),
    ],
)
async def test_go_openai_protocols_send_stable_session_and_user_agent(
    provider: str,
    response_factory: Callable[..., dict[str, Any]],
    expected_path: str,
) -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=response_factory(tool_call=False))

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    settings = Settings(_env_file=None, opencode_go_api_key="test-key")
    model = resolve_model(
        f"{provider}/exact-model-id",
        settings,
        session_id="stable-session-id",
        http_client=client,
    )

    result = await Agent(
        model,
        model_settings=resolve_model_settings(f"{provider}/exact-model-id"),
    ).run("go")

    assert result.output == "done"
    assert requests[0].url.path == expected_path
    assert requests[0].headers["x-opencode-session"] == "stable-session-id"
    assert requests[0].headers["user-agent"] == "ctf-agent/0.1"
    await client.aclose()


@pytest.mark.asyncio
async def test_go_adapter_does_not_hide_rate_limit_behind_sdk_retries() -> None:
    requests = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        return httpx2.Response(429, json={"error": {"message": "rate limit"}})

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    settings = Settings(_env_file=None, opencode_go_api_key="test-key")
    model = resolve_model(
        "go-chat/exact-model-id",
        settings,
        session_id="stable-session-id",
        http_client=client,
    )

    with pytest.raises(ModelHTTPError) as exc_info:
        await Agent(
            model,
            model_settings=resolve_model_settings("go-chat/exact-model-id"),
        ).run("go")

    assert exc_info.value.status_code == 429
    assert requests == 1
    await client.aclose()
