# -*- coding: utf-8 -*-
"""
DeepSeek AI 客户端
==================

只做一件事：把设置面板里的参数翻译成 DeepSeek Chat Completions 请求，
并把返回文本交回业务层。网络调用放在这里，core.py 保持纯粹。

注意（DeepSeek 官方规则）：
- 思考模式开关：thinking.type = enabled / disabled，需放在 extra_body 里。
- 思考强度：reasoning_effort = low / high / max。
- 思考模式下 temperature / top_p 不生效，所以这里只在非思考模式传它们。
- 联网搜索是服务端工具：tools=[{"type":"deepseek_web_search"}]。
  工具开启后服务端也会忽略 temperature / top_p。
"""

from __future__ import annotations

from typing import Any

from core import DEFAULT_AI_SETTINGS


class AIError(Exception):
    """面向用户展示的 AI 错误，文案已经是中文。"""


def _friendly_error(exc: Exception) -> str:
    """把 SDK 异常转成能直接显示在界面上的中文提示。"""
    text = str(exc)
    lowered = text.lower()
    if "401" in text or "authentication" in lowered or "invalid api key" in lowered:
        return "API Key 无效或已过期，请在设置里检查。"
    if "402" in text or "insufficient" in lowered or "balance" in lowered:
        return "DeepSeek 账户余额不足，请充值后再试。"
    if "429" in text or "rate limit" in lowered:
        return "请求过于频繁，请稍后再试。"
    if "timeout" in lowered or "timed out" in lowered:
        return "请求超时，请检查网络后重试。"
    if "connection" in lowered or "network" in lowered or "unreachable" in lowered:
        return "网络连接失败，请检查代理或网络设置。"
    return f"AI 请求失败：{text[:300]}"


def build_analysis_prompt(
    item: dict[str, Any],
    settings: dict[str, Any],
    type_prompt: str = "",
) -> tuple[str, str]:
    """根据背诵类型拼出 (系统提示词, 用户提示词)。"""
    recite_type = str(item.get("type") or "").strip()
    template = str(type_prompt or "").strip()

    system_prompt = str(
        settings.get("systemPrompt") or DEFAULT_AI_SETTINGS["systemPrompt"]
    ).strip()

    lines = [f"背诵内容：{item.get('title', '')}"]
    note = str(item.get("note") or "").strip()
    if note:
        lines.append(f"备注：{note}")
    if recite_type:
        lines.append(f"类型：{recite_type}")
    lines.append("")
    if template:
        lines.append(template)
    lines.append("只输出解析正文，不要复述题目，不要加标题。")
    return system_prompt, "\n".join(lines)


def call_deepseek(
    settings: dict[str, Any],
    user_prompt: str | None = None,
    system_prompt: str | None = None,
    *,
    quick: bool = False,
    messages: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    调用 Chat Completions，返回 {"content", "model", "usage"}。

    普通解析传 user_prompt；多轮追问传 messages（含 history 与本轮 user）。
    quick=True 用于测试连接：强制关闭思考与工具，少量 token，避免额外费用。
    """
    api_key = str(settings.get("apiKey") or "").strip()
    if not api_key:
        raise AIError("请先在设置里填写 DeepSeek API Key")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AIError("缺少 openai 依赖，请先执行：python -m pip install openai") from exc

    base_url = str(settings.get("baseUrl") or "").strip() or DEFAULT_AI_SETTINGS["baseUrl"]
    model = str(settings.get("model") or "").strip() or DEFAULT_AI_SETTINGS["model"]
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0)

    thinking = False if quick else bool(settings.get("thinking"))
    extra_body: dict[str, Any] = {
        "thinking": {"type": "enabled" if thinking else "disabled"}
    }

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [],
        "stream": False,
        "extra_body": extra_body,
    }
    if system_prompt:
        kwargs["messages"].append({"role": "system", "content": system_prompt})
    if messages is not None:
        for msg in messages:
            role = str(msg.get("role") or "")
            content = str(msg.get("content") or "")
            if role in ("user", "assistant") and content:
                kwargs["messages"].append({"role": role, "content": content})
    else:
        kwargs["messages"].append({"role": "user", "content": str(user_prompt or "")})

    if quick:
        kwargs["max_tokens"] = 64
    else:
        # 不能写成 `x or 默认值`：top_p=0 / temperature=0 是合法值，会被误当成空值。
        max_tokens = settings.get("maxTokens")
        kwargs["max_tokens"] = int(max_tokens) if max_tokens is not None else 2048
        if thinking:
            # 思考模式下 temperature / top_p 不生效，不传给服务端。
            effort = str(settings.get("reasoningEffort") or "high").strip().lower()
            if effort not in ("low", "high", "max"):
                effort = "high"
            kwargs["reasoning_effort"] = effort
        else:
            temperature = settings.get("temperature")
            top_p = settings.get("topP")
            kwargs["temperature"] = float(temperature) if temperature is not None else 1.0
            kwargs["top_p"] = float(top_p) if top_p is not None else 1.0

        # 服务端工具：联网搜索由 DeepSeek 完成，无需自己实现工具循环。
        if settings.get("webSearch"):
            kwargs["tools"] = [{"type": "deepseek_web_search"}]

    try:
        response = client.chat.completions.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        raise AIError(_friendly_error(exc)) from exc

    message = response.choices[0].message if response.choices else None
    content = str(getattr(message, "content", "") or "").strip()
    if not content:
        raise AIError("AI 没有返回内容，请调整提示词或稍后重试")

    usage = getattr(response, "usage", None)
    usage_info = {
        "promptTokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
        "completionTokens": getattr(usage, "completion_tokens", 0) if usage else 0,
    }
    return {"content": content, "model": model, "usage": usage_info}


def test_connection(settings: dict[str, Any]) -> dict[str, Any]:
    """用最省的方式测试 API Key 与网络是否可用。"""
    result = call_deepseek(settings, "请只回复：连接成功", quick=True)
    return {"ok": True, "message": f"连接成功（{result['model']}）"}
