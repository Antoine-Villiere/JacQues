from __future__ import annotations

from typing import Any

from litellm import completion

from ..config import Settings


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def available(self) -> bool:
        return bool(self.settings.litellm_api_key or self.settings.litellm_api_base)

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        stream: bool | None = None,
    ) -> dict[str, Any]:
        use_stream = self.settings.llm_streaming if stream is None else stream
        kwargs = self._base_kwargs(model)
        kwargs["messages"] = messages
        kwargs["temperature"] = 0.2
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if use_stream:
            kwargs["stream"] = True
            return self._consume_stream(completion(**kwargs))

        response = completion(**kwargs)
        return self._message_from_response(response)

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[object, dict[str, Any]]:
        kwargs = self._base_kwargs(model)
        kwargs["messages"] = messages
        kwargs["temperature"] = 0.2
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        kwargs["stream"] = True

        state: dict[str, Any] = {
            "content_parts": [],
            "tool_calls": {},
        }

        def iterator():
            for chunk in completion(**kwargs):
                chunk_dict = self._to_dict(chunk)
                choices = chunk_dict.get("choices") or []
                if not choices:
                    continue
                delta = self._to_dict(choices[0].get("delta", {}))
                if not delta:
                    continue
                content = delta.get("content")
                if content:
                    state["content_parts"].append(content)
                    yield content
                for tool_call in delta.get("tool_calls") or []:
                    call = self._to_dict(tool_call)
                    index = call.get("index", 0)
                    entry = state["tool_calls"].setdefault(
                        index,
                        {
                            "id": call.get("id"),
                            "type": call.get("type", "function"),
                            "function": {"name": "", "arguments": ""},
                        },
                    )
                    if call.get("id"):
                        entry["id"] = call["id"]
                    function = call.get("function") or {}
                    if function.get("name"):
                        entry["function"]["name"] += function["name"]
                    if function.get("arguments"):
                        entry["function"]["arguments"] += function["arguments"]

        return iterator(), state

    def _base_kwargs(self, model: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self._normalize_model(model)}
        if self.settings.litellm_provider:
            kwargs["custom_llm_provider"] = self.settings.litellm_provider
        if self.settings.litellm_api_key:
            kwargs["api_key"] = self.settings.litellm_api_key
        if self.settings.litellm_api_base:
            kwargs["api_base"] = self.settings.litellm_api_base
        return kwargs

    def _normalize_model(self, model: str) -> str:
        if self.settings.litellm_provider:
            prefix = f"{self.settings.litellm_provider}/"
            if model.startswith(prefix):
                return model[len(prefix) :]
        return model

    def _message_from_response(self, response: Any) -> dict[str, Any]:
        message = response.choices[0].message
        if isinstance(message, dict):
            return message
        if hasattr(message, "model_dump"):
            return message.model_dump()
        if hasattr(message, "dict"):
            return message.dict()
        return {"content": str(message)}

    def _consume_stream(self, stream: Any) -> dict[str, Any]:
        content_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}

        for chunk in stream:
            chunk_dict = self._to_dict(chunk)
            choices = chunk_dict.get("choices") or []
            if not choices:
                continue
            delta = self._to_dict(choices[0].get("delta", {}))
            if not delta:
                continue
            content = delta.get("content")
            if content:
                content_parts.append(content)
            for tool_call in delta.get("tool_calls") or []:
                call = self._to_dict(tool_call)
                index = call.get("index", 0)
                entry = tool_calls.setdefault(
                    index,
                    {
                        "id": call.get("id"),
                        "type": call.get("type", "function"),
                        "function": {"name": "", "arguments": ""},
                    },
                )
                if call.get("id"):
                    entry["id"] = call["id"]
                function = call.get("function") or {}
                if function.get("name"):
                    entry["function"]["name"] += function["name"]
                if function.get("arguments"):
                    entry["function"]["arguments"] += function["arguments"]

        message: dict[str, Any] = {"content": "".join(content_parts).strip()}
        if tool_calls:
            ordered = []
            for idx in sorted(tool_calls):
                entry = tool_calls[idx]
                if not entry.get("id"):
                    entry["id"] = f"call_{idx}"
                ordered.append(entry)
            message["tool_calls"] = ordered
        return message

    def _to_dict(self, obj: Any) -> dict[str, Any]:
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "dict"):
            return obj.dict()
        return {}
