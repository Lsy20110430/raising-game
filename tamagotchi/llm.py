"""DeepSeek 调用封装。API Key 从环境变量或 .env 读取，绝不下发到前端。"""

import json
import os
import time
import urllib.error
import urllib.request

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
TIMEOUT = 60

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class LLMError(RuntimeError):
    pass


def load_env():
    path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def api_key():
    load_env()
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise LLMError("未配置 DEEPSEEK_API_KEY，请在 tamagotchi/.env 中填写")
    return key


def _request_once(messages, json_mode, temperature, max_tokens):
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key(),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:300]
        raise LLMError("接口返回 {}：{}".format(exc.code, detail)) from exc
    except Exception as exc:
        raise LLMError("网络异常：{}".format(exc)) from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMError("返回格式异常：{}".format(str(data)[:200])) from exc
    if content is None or not str(content).strip():
        raise LLMError("模型返回了空内容")
    return str(content)


def chat(messages, json_mode=False, temperature=1.0, max_tokens=600, retries=2):
    """网关偶发返回空响应，空内容/解析失败时降温重试，避免把偶发错误丢给玩家。"""
    last_error = None
    for attempt in range(retries + 1):
        try:
            return _request_once(
                messages, json_mode,
                max(0.3, temperature - 0.25 * attempt),
                max_tokens,
            )
        except LLMError as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last_error


def chat_json(messages, retries=2, **kwargs):
    last_error = None
    for attempt in range(retries + 1):
        raw = chat(messages, json_mode=True, **kwargs).strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw.split("\n", 1)[-1] if "\n" in raw else raw
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            last_error = LLMError("模型未返回合法 JSON：{}".format(raw[:200]))
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
    raise last_error
