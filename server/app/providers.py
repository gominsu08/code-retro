"""Provider adapters preserve the same bounded agent loop and evidence checks."""
from dataclasses import dataclass
from types import SimpleNamespace

from openai import OpenAI

from .config import get_settings


def gemini_schema(schema):
    definitions = schema.get("$defs", {})
    def expand(value):
        if isinstance(value, list):
            return [expand(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            return expand(definitions[value["$ref"].split("/")[-1]])
        return {key: ({name: expand(definition) for name, definition in item.items()} if key == "properties" else expand(item))
                for key, item in value.items() if key not in ("$defs", "title", "additionalProperties")}
    return expand(schema)


@dataclass
class GeminiCall:
    call_id: str
    name: str
    arguments: str
    provider_tool_call: dict
    type: str = "function_call"

    def model_dump(self, **_kwargs):
        return self.__dict__.copy()


def chat_messages(instructions, items):
    result = [{"role": "system", "content": instructions}]
    for item in items:
        if item.get("type") == "function_call":
            call = item.get("provider_tool_call") or {"id": item["call_id"], "type": "function", "function": {"name": item["name"], "arguments": item["arguments"]}}
            if result[-1]["role"] == "assistant" and result[-1].get("tool_calls"):
                result[-1]["tool_calls"].append(call)
            else:
                result.append({"role": "assistant", "content": None, "tool_calls": [call]})
        elif item.get("type") == "function_call_output":
            result.append({"role": "tool", "tool_call_id": item["call_id"], "content": item["output"]})
        else:
            result.append({"role": item["role"], "content": item["content"]})
    return result


class GeminiProvider:
    def __init__(self, client=None):
        self.client = client or OpenAI(api_key=get_settings().gemini_api_key.get_secret_value(),
                                      base_url="https://generativelanguage.googleapis.com/v1beta/openai/", max_retries=0, timeout=60)
        self.responses = self

    def create(self, **request):
        # Gemini 2.5 does not combine tools with response_format. A final submission
        # function carries the document schema without enabling that combination.
        tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                  **({"parameters": gemini_schema(t["parameters"])} if t["parameters"].get("properties") else {})}} for t in request["tools"]]
        tools.append({"type": "function", "function": {"name": "submit_explanation", "description": "코드 확인을 마친 간결한 개발 회고를 최종 제출한다. 다른 도구와 동시에 호출하지 않는다.",
                                                          "parameters": gemini_schema(request["text"]["format"]["schema"])}})
        messages = chat_messages(request["instructions"] + "\n최종 설명은 반드시 submit_explanation 도구의 인자로 제출한다. 먼저 read_code로 근거를 읽고, 수정 작업에서는 get_review_context를 호출한다.", request["input"])
        response = self.client.chat.completions.create(model=request["model"], messages=messages, tools=tools, tool_choice="auto", max_tokens=request["max_output_tokens"], temperature=0.2)
        choice = response.choices[0]
        message = choice.message
        raw_calls = message.tool_calls or []
        submitted = [call for call in raw_calls if call.function.name == "submit_explanation"]
        calls = [GeminiCall(call.id, call.function.name, call.function.arguments, call.model_dump(exclude_none=True)) for call in raw_calls if call.function.name != "submit_explanation"]
        # Only a submission on its own is final; tool results must be observed first.
        if submitted and not calls:
            output_text = submitted[0].function.arguments
        else:
            output_text = message.content or ""
        status = "completed" if choice.finish_reason in ("stop", "tool_calls") else "incomplete"
        return SimpleNamespace(output=calls, output_text=output_text, status=status, usage=response.usage)

    def close(self):
        self.client.close()


def create_provider():
    settings = get_settings()
    if settings.ai_provider == "gemini":
        return GeminiProvider()
    return OpenAI(api_key=settings.openai_api_key.get_secret_value(), max_retries=0, timeout=60)
