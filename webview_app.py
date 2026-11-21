# -*- coding: utf-8 -*-
"""
拾忆 · 艾宾浩斯背诵助手 —— WebView2 桌面外壳
=============================================

用 pywebview 的 Edge WebView2 内核承载 web/ 下的 HTML/CSS/JS 界面。
Python 侧只暴露一组很薄的 API，所有业务规则仍然由 core.ReviewCore 负责。

启动：
    python webview_app.py
调试（打开 WebView2 开发者工具）：
    python webview_app.py --debug
"""

from __future__ import annotations

import json
import re
import sys
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import webview

from ai_client import AIError, build_analysis_prompt, call_deepseek, test_connection
from core import APP_NAME, APP_VERSION, ICON_FILE, WEB_DIR, ReviewCore

# 更新检查：对接项目的 GitHub Releases。
UPDATE_REPO = "Sheldon-walker/shiyi-recite-assistant"
UPDATE_API = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
UPDATE_PAGE = f"https://github.com/{UPDATE_REPO}/releases"


def version_tuple(text: str) -> tuple[int, ...]:
    """从 'v0.1.0' 之类的字符串里提取数字版本，用于比较大小。"""
    nums = re.findall(r"\d+", str(text or ""))
    return tuple(int(n) for n in nums) if nums else (0,)


def fetch_latest_release() -> dict[str, Any]:
    """读取 GitHub 最新 release；网络异常交给调用方转成中文提示。"""
    request = urllib.request.Request(
        UPDATE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ShiYi-Recite-Assistant",
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def guarded(func):
    """把未预期的异常转成前端可显示的结果，避免 JS 端出现未捕获拒绝。"""
    def wrapper(self: "Api", *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return func(self, *args, **kwargs)
        except AIError as exc:
            return {"ok": False, "message": str(exc), "kind": "error"}
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return {
                "ok": False,
                "message": f"操作失败：{exc}",
                "kind": "error",
            }
    wrapper.__name__ = func.__name__
    return wrapper


def normalize_conversation(
    messages: list[Any],
    system_prompt: str,
) -> tuple[str, list[dict[str, str]]]:
    """把本地对话历史整理成 DeepSeek 要求的 user/assistant 严格交替序列。

    本地 messages 的第一条是初始解析（assistant）。它不能作为 API 的第一条
    消息，否则会报 "an assistant message must follow a user message"。
    这里把它移到系统提示词里作背景；其余问答保留，合并连续相同角色。
    """
    background = ""
    body = messages
    if body and isinstance(body[0], dict) and body[0].get("role") == "assistant":
        background = str(body[0].get("content") or "").strip()
        body = body[1:]

    normalized: list[dict[str, str]] = []
    for msg in body:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = str(msg.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        if normalized and normalized[-1]["role"] == role:
            normalized[-1]["content"] += "\n\n" + content
        else:
            normalized.append({"role": role, "content": content})

    final_system = system_prompt
    if background:
        final_system = (
            (system_prompt + "\n\n" if system_prompt else "")
            + "以下是这条背诵内容已有的解析，作为对话背景参考：\n"
            + background[:8000]
        )
    return final_system, normalized


def append_user_message(messages: list[dict[str, str]], content: str) -> None:
    """追加一条 user 消息，若上一条也是 user 则合并，保持严格交替。"""
    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] += "\n\n" + content
    else:
        messages.append({"role": "user", "content": content})


class Api:
    """暴露给 window.pywebview.api 的方法，全部返回可 JSON 序列化的字典。"""

    def __init__(self, core: ReviewCore) -> None:
        self._core = core

    @guarded
    def get_state(self) -> dict[str, Any]:
        return {"ok": True, "state": self._core.state()}

    @guarded
    def get_about_info(self) -> dict[str, Any]:
        """关于弹窗需要的静态信息，无需联网。"""
        return {
            "ok": True,
            "version": APP_VERSION,
            "repo": UPDATE_REPO,
            "releasesUrl": UPDATE_PAGE,
        }

    @guarded
    def check_update(self) -> dict[str, Any]:
        """从 GitHub Releases 读取最新版本，与当前版本比较。"""
        try:
            release = fetch_latest_release()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {
                    "ok": True,
                    "latestVersion": "",
                    "hasUpdate": False,
                    "message": "该仓库暂无发布版本",
                }
            return {
                "ok": False,
                "message": f"检查更新失败：GitHub 返回 {exc.code}",
                "kind": "error",
            }
        except (urllib.error.URLError, TimeoutError, OSError):
            return {
                "ok": False,
                "message": "网络连接失败，请检查网络后重试",
                "kind": "error",
            }
        except (ValueError, json.JSONDecodeError):
            return {"ok": False, "message": "更新信息解析失败", "kind": "error"}

        latest = str(release.get("tag_name") or "").strip()
        has_update = bool(latest) and version_tuple(latest) > version_tuple(APP_VERSION)
        download_url = ""
        for asset in release.get("assets") or []:
            name = str(asset.get("name") or "").lower()
            if name.endswith(".exe"):
                download_url = str(asset.get("browser_download_url") or "")
                break

        return {
            "ok": True,
            "latestVersion": latest,
            "hasUpdate": has_update,
            "publishedAt": str(release.get("published_at") or "")[:10],
            "releaseUrl": str(release.get("html_url") or UPDATE_PAGE),
            "downloadUrl": download_url,
            "notes": str(release.get("body") or "")[:4000],
            "message": (
                f"发现新版本 {latest}" if has_update
                else (f"当前已是最新版本 {latest}" if latest else "该仓库暂无发布版本")
            ),
        }

    @guarded
    def open_release_page(self) -> dict[str, Any]:
        """用系统默认浏览器打开 GitHub Releases 页面。"""
        try:
            opened = webbrowser.open(UPDATE_PAGE, new=2)
        except Exception:  # noqa: BLE001
            opened = False
        if not opened:
            return {"ok": False, "message": "无法自动打开浏览器，请手动访问 GitHub 仓库的 Releases 页面", "kind": "error"}
        return {"ok": True, "message": "已在浏览器中打开更新日志"}

    @guarded
    def open_external_url(self, url: str) -> dict[str, Any]:
        """只放行本项目 GitHub 仓库的链接，避免被当成任意 URL 打开器。"""
        target = str(url or "").strip()
        prefix = f"https://github.com/{UPDATE_REPO}/"
        if not target.startswith(prefix):
            return {"ok": False, "message": "链接无效", "kind": "error"}
        try:
            opened = webbrowser.open(target, new=2)
        except Exception:  # noqa: BLE001
            opened = False
        if not opened:
            return {"ok": False, "message": "无法自动打开浏览器，请在 GitHub 仓库手动下载", "kind": "error"}
        return {"ok": True, "message": "已在浏览器中打开下载页"}

    @guarded
    def add_item(
        self,
        title: str,
        note: str,
        intervals: list[Any],
        recite_type: str | None = None,
        custom_type: str | None = None,
    ) -> dict[str, Any]:
        return self._core.add_item(title, note, intervals, recite_type, custom_type)

    @guarded
    def update_item(
        self,
        item_id: str,
        title: str,
        note: str,
        recite_type: str | None = None,
        custom_type: str | None = None,
    ) -> dict[str, Any]:
        return self._core.update_item(
            item_id, title, note, recite_type, custom_type
        )

    @guarded
    def save_intervals(self, item_id: str, intervals: list[Any]) -> dict[str, Any]:
        return self._core.save_intervals(item_id, intervals)

    @guarded
    def complete_review(self, item_id: str, due_iso: str) -> dict[str, Any]:
        return self._core.complete_review(item_id, due_iso)

    @guarded
    def delete_item(self, item_id: str) -> dict[str, Any]:
        return self._core.delete_item(item_id)

    @guarded
    def set_appearance(self, mode: str) -> dict[str, Any]:
        return self._core.set_appearance(mode)

    @guarded
    def get_ai_settings(self) -> dict[str, Any]:
        return self._core.get_ai_settings()

    @guarded
    def get_recite_types(self) -> dict[str, Any]:
        return self._core.get_recite_types()

    @guarded
    def save_recite_types(self, types: list[Any]) -> dict[str, Any]:
        return self._core.save_recite_types(types)

    @guarded
    def save_ai_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        return self._core.save_ai_settings(settings)

    @guarded
    def test_ai_connection(self) -> dict[str, Any]:
        settings = self._core.get_ai_settings()["settings"]
        return test_connection(settings)

    @guarded
    def generate_analysis(self, item_id: str, force: bool = False) -> dict[str, Any]:
        """按背诵类型生成解析并缓存；force=True 表示重新生成。"""
        item = self._core.find_item(item_id)
        if item is None:
            return {"ok": False, "message": "这条内容已经不存在，请刷新后重试", "kind": "error"}

        if item.get("analysis") and not force:
            return {
                "ok": True,
                "message": "",
                "cached": True,
                "analysis": item["analysis"],
            }

        settings = self._core.get_ai_settings()["settings"]
        type_prompt = self._core.type_prompt(str(item.get("type") or ""))
        system_prompt, user_prompt = build_analysis_prompt(item, settings, type_prompt)
        result = call_deepseek(settings, user_prompt, system_prompt)
        saved = self._core.save_analysis(
            item_id, result["content"], result["model"]
        )
        if not saved["ok"]:
            return saved

        return {
            "ok": True,
            "message": "AI 解析已生成",
            "analysis": self._core.find_item(item_id)["analysis"],
            "usage": result["usage"],
        }

    @guarded
    def chat_analysis(
        self, item_id: str, message: str, quote: str = ""
    ) -> dict[str, Any]:
        """就已有解析继续追问，带上对话上下文与划词引用。"""
        item = self._core.find_item(item_id)
        if item is None:
            return {"ok": False, "message": "这条内容已经不存在，请刷新后重试", "kind": "error"}
        analysis = item.get("analysis")
        if not isinstance(analysis, dict):
            return {"ok": False, "message": "请先生成 AI 解析再追问", "kind": "error"}

        question = str(message or "").strip()
        if not question:
            return {"ok": False, "message": "请输入追问内容", "kind": "error"}
        if len(question) > 1000:
            return {"ok": False, "message": "追问内容请控制在 1000 字以内", "kind": "error"}

        clean_quote = str(quote or "").strip()[:500]
        settings = self._core.get_ai_settings()["settings"]
        # 系统提示词是整体设定：首次解析和后续追问统一使用，不在这里追加额外指令。
        system_prompt = str(settings.get("systemPrompt") or "").strip()

        full_system, history = normalize_conversation(
            list(analysis.get("messages") or []), system_prompt
        )
        # 只带最近若干轮，避免上下文过长；裁剪时不要从中间切开一对问答。
        if len(history) > 30:
            history = history[-30:]
            if history[0]["role"] == "assistant":
                history = history[1:]

        user_content = question
        if clean_quote:
            user_content = f"你引用的解析内容：\n{clean_quote}\n\n你的追问：{question}"
        append_user_message(history, user_content)

        result = call_deepseek(
            settings,
            system_prompt=full_system,
            messages=history,
        )
        saved = self._core.append_chat(
            item_id, question, result["content"], clean_quote
        )
        if not saved["ok"]:
            return saved
        return {
            "ok": True,
            "message": "已回复",
            "analysis": self._core.find_item(item_id)["analysis"],
            "usage": result["usage"],
        }

    @guarded
    def regenerate_message(self, item_id: str, index: int) -> dict[str, Any]:
        """重新生成某条 AI 消息；第一条会按类型提示词重新生成整篇解析。"""
        item = self._core.find_item(item_id)
        if item is None:
            return {"ok": False, "message": "这条内容已经不存在，请刷新后重试", "kind": "error"}
        analysis = item.get("analysis")
        if not isinstance(analysis, dict):
            return {"ok": False, "message": "请先生成 AI 解析", "kind": "error"}
        messages = analysis.get("messages") or []
        try:
            idx = int(index)
        except (TypeError, ValueError):
            return {"ok": False, "message": "消息序号无效", "kind": "error"}
        if idx < 0 or idx >= len(messages):
            return {"ok": False, "message": "这条消息已经不存在", "kind": "error"}
        if messages[idx].get("role") != "assistant":
            return {"ok": False, "message": "只能重新生成 AI 的消息", "kind": "error"}

        settings = self._core.get_ai_settings()["settings"]
        system_prompt = str(settings.get("systemPrompt") or "").strip()
        if idx == 0:
            # 首次解析按该类型的提示词重做，后续对话全部丢弃。
            type_prompt = self._core.type_prompt(str(item.get("type") or ""))
            _system, user_prompt = build_analysis_prompt(item, settings, type_prompt)
            result = call_deepseek(settings, user_prompt, system_prompt)
            new_messages = [{"role": "assistant", "content": result["content"]}]
            saved = self._core.save_chat_messages(
                item_id, new_messages, text=result["content"]
            )
        else:
            full_system, history = normalize_conversation(
                list(messages[:idx]), system_prompt
            )
            # history 必须以 user 结尾，模型才会接着生成 assistant。
            if history and history[-1]["role"] == "assistant":
                history = history[:-1]
            result = call_deepseek(
                settings, system_prompt=full_system, messages=history
            )
            # 界面上仍保留第一条初始解析，方便用户继续查看与操作。
            initial = [messages[0]] if messages and messages[0].get("role") == "assistant" else []
            new_messages = initial + history + [
                {"role": "assistant", "content": result["content"]}
            ]
            saved = self._core.save_chat_messages(item_id, new_messages)
        if not saved["ok"]:
            return saved
        return {
            "ok": True,
            "message": "已重新生成该条回复",
            "analysis": self._core.find_item(item_id)["analysis"],
        }

    @guarded
    def edit_chat(self, item_id: str, index: int, text: str) -> dict[str, Any]:
        """编辑自己的某条追问：清掉它之后的对话，并以新内容重新提问。"""
        item = self._core.find_item(item_id)
        if item is None:
            return {"ok": False, "message": "这条内容已经不存在，请刷新后重试", "kind": "error"}
        analysis = item.get("analysis")
        if not isinstance(analysis, dict):
            return {"ok": False, "message": "请先生成 AI 解析", "kind": "error"}
        messages = analysis.get("messages") or []
        try:
            idx = int(index)
        except (TypeError, ValueError):
            return {"ok": False, "message": "消息序号无效", "kind": "error"}
        if idx < 0 or idx >= len(messages):
            return {"ok": False, "message": "这条消息已经不存在", "kind": "error"}
        if messages[idx].get("role") != "user":
            return {"ok": False, "message": "只能编辑自己的消息", "kind": "error"}

        question = str(text or "").strip()
        if not question:
            return {"ok": False, "message": "请输入追问内容", "kind": "error"}
        if len(question) > 1000:
            return {"ok": False, "message": "追问内容请控制在 1000 字以内", "kind": "error"}

        settings = self._core.get_ai_settings()["settings"]
        full_system, history = normalize_conversation(
            list(messages[:idx]), str(settings.get("systemPrompt") or "").strip()
        )
        edited_content = question[:1000]
        quote = str(messages[idx].get("quote") or "").strip()
        if quote:
            edited_content = f"你引用的解析内容：\n{quote[:500]}\n\n{edited_content}"
        append_user_message(history, edited_content)

        result = call_deepseek(
            settings,
            system_prompt=full_system,
            messages=history,
        )
        initial = [messages[0]] if messages and messages[0].get("role") == "assistant" else []
        new_messages = initial + history + [
            {"role": "assistant", "content": result["content"]}
        ]
        saved = self._core.save_chat_messages(item_id, new_messages)
        if not saved["ok"]:
            return saved
        return {
            "ok": True,
            "message": "已编辑追问并重新生成后续对话",
            "analysis": self._core.find_item(item_id)["analysis"],
        }

    @guarded
    def chat_edit(self, item_id: str, index: int, text: str) -> dict[str, Any]:
        """兼容别名：早期前端曾调用 chat_edit，实际逻辑与 edit_chat 相同。"""
        return self.edit_chat(item_id, index, text)

    @guarded
    def delete_chat_message(self, item_id: str, index: int) -> dict[str, Any]:
        """删除自己的一条追问及其回复，不影响其他对话或整份解析。"""
        return self._core.delete_chat_message(item_id, index)

    @guarded
    def clear_analysis(self, item_id: str) -> dict[str, Any]:
        return self._core.clear_analysis(item_id)

    @guarded
    def refresh(self) -> dict[str, Any]:
        return self._core.refresh()


def _selftest(window: Any) -> None:
    """--selftest：检查打包后的窗口是否成功加载 JS API 与界面，然后退出。"""
    checks = {
        "title": "document.title",
        "apiReady": "!!(window.pywebview && window.pywebview.api)",
        "theme": "document.documentElement.dataset.theme",
        "pageTitle": "document.querySelector('#page-title').textContent",
        "taskCards": "document.querySelectorAll('.task-card').length",
        "saveStatus": "document.querySelector('#save-status').textContent",
    }

    def run() -> None:
        time.sleep(2.5)
        result: dict[str, Any] = {}
        for name, js in checks.items():
            try:
                result[name] = window.evaluate_js(js)
            except Exception as exc:  # noqa: BLE001
                result[name] = f"ERROR: {exc}"

        # 顺带验证新增的设置面板与类型选项能在打包环境里打开。
        try:
            window.evaluate_js("document.querySelector('#btn-settings').click()")
            time.sleep(1.0)
            result["settingsTitle"] = window.evaluate_js(
                "document.querySelector('.modal h2')?.textContent"
            )
            result["apiKeyField"] = window.evaluate_js(
                "!!document.querySelector('#ai-key')"
            )
            window.evaluate_js("document.querySelector('[data-action=close-modal]').click()")
        except Exception as exc:  # noqa: BLE001
            result["settingsError"] = f"ERROR: {exc}"

        Path("selftest_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        window.destroy()

    # 由 webview.start(func=...) 在窗口就绪后的工作线程里调用。
    return run


def main() -> None:
    index_file = WEB_DIR / "index.html"
    if not index_file.exists():
        raise SystemExit(f"找不到前端入口文件：{index_file}")

    # 允许本地 file:// 页面加载同目录的 CSS/JS。
    webview.settings["ALLOW_FILE_URLS"] = True

    core = ReviewCore()
    api = Api(core)

    window = webview.create_window(
        title=APP_NAME,
        url=index_file.as_uri(),
        js_api=api,
        width=1180,
        height=780,
        min_size=(760, 520),
        resizable=True,
        background_color="#F4F5F9",
        # 允许划选文字，否则 pywebview 注入的 user-select:none 会让引用功能失效。
        text_select=True,
    )

    icon = str(ICON_FILE) if ICON_FILE.exists() else None
    selftest = "--selftest" in sys.argv
    try:
        webview.start(
            func=_selftest(window) if selftest and window else None,
            gui="edgechromium",
            debug="--debug" in sys.argv,
            icon=icon,
        )
    except Exception as exc:  # noqa: BLE001
        # WebView2 Runtime 缺失时给出可操作的提示，而不是静默退出。
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            APP_NAME,
            "无法启动 WebView2 界面。\n\n"
            f"原因：{exc}\n\n"
            "请确认已安装 Microsoft Edge WebView2 Runtime（Windows 10/11 通常自带）。",
        )
        root.destroy()
        raise


if __name__ == "__main__":
    main()
