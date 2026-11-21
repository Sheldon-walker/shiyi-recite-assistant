# -*- coding: utf-8 -*-
"""
拾忆 · 艾宾浩斯背诵助手 —— 纯业务后端
======================================

这一层不依赖任何界面库，只负责：

1. 定义常量与日期工具；
2. 读取 / 校验 / 原子写入 review_data.json；
3. 完成添加、编辑、完成、删除、调整单条时间轴等业务操作；
4. 把数据整理成前端可以直接渲染的视图模型。

WebView2 前端（web/ 目录）只负责显示和交互，所有业务判断都在这里，
这样以后换界面（Tkinter / Web / 命令行）都不用重写规则。
"""

from __future__ import annotations

import copy
import json
import os
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# ------------------------------------------------------------------
# 一、常量
# ------------------------------------------------------------------
APP_NAME = "拾忆 · 艾宾浩斯背诵助手"
APP_VERSION = "0.1.0"

IS_FROZEN = bool(getattr(sys, "frozen", False))

# 源码运行时数据写在 core.py 旁边；exe 运行时写在 exe 旁边。
APP_DIR = (
    Path(sys.executable).resolve().parent
    if IS_FROZEN
    else Path(__file__).resolve().parent
)
# onefile 打包后只读资源在 _MEIPASS 里。
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))

DATA_FILE = APP_DIR / "review_data.json"
ICON_FILE = RESOURCE_DIR / "assets" / "app_icon.ico"
WEB_DIR = RESOURCE_DIR / "web"

DEFAULT_REVIEW_INTERVALS: tuple[int, ...] = (1, 2, 4, 7, 15)
EBBINGHAUS_INTERVALS: tuple[int, ...] = (
    1, 2, 4, 7, 15, 30, 60, 120, 240, 365, 730, 1095, 1825, 3650,
)

MIN_INTERVAL_NODE_COUNT = 1
MAX_INTERVAL_NODE_COUNT = 10
MAX_INTERVAL_DAY = 3650

APPEARANCE_LABELS = {
    "system": "跟随系统",
    "light": "浅色",
    "dark": "深色",
}
APPEARANCE_MODES = {label: mode for mode, label in APPEARANCE_LABELS.items()}

WEEKDAYS_CN = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

# 标题 / 备注长度限制，和旧版弹窗保持一致。
MAX_TITLE_LENGTH = 60
MAX_NOTE_LENGTH = 1000

# 背诵类型：完全由用户在设置里维护，默认给三种常见类型。
DEFAULT_RECITE_TYPES: tuple[str, ...] = ("诗词", "古文", "英语单词")
DEFAULT_RECITE_TYPE = "诗词"
MAX_RECITE_TYPE_NAME = 20
MAX_TYPE_PROMPT_LENGTH = 2000
MAX_CHAT_MESSAGES = 40

# 各类型的默认解析提示词，可在设置里逐条修改。
DEFAULT_TYPE_PROMPTS: dict[str, str] = {
    "诗词": "请简洁解析这首诗词：1）白话翻译；2）核心意象与情感；3）重点字词。分点输出，不要长篇大论。",
    "古文": "请简洁解析这段古文：1）重点实词和虚词；2）白话翻译；3）主旨。分点输出，不要长篇大论。",
    "英语单词": "请简洁解析这个英语单词：1）词根词缀拆解，说明每个部分的含义；2）同源词，每个附简短中文释义。总量控制在 15 行以内。",
}
# 用户把某个类型的提示词清空时，用这条兜底。
GENERIC_TYPE_PROMPT = "请简洁解析这条背诵内容的关键知识点，分点输出，不要长篇大论。"


def trim_chat_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """裁剪历史时保留初始解析，并保证剩下的问答仍以 user 开头、严格交替。"""
    if len(messages) <= MAX_CHAT_MESSAGES:
        return messages
    head = [messages[0]] if messages and messages[0].get("role") == "assistant" else []
    body = messages[len(head):]
    limit = MAX_CHAT_MESSAGES - len(head)
    if len(body) > limit:
        body = body[-limit:]
        # 从中间切开一对问答时，丢掉落单的 assistant，避免连续两条 AI 消息。
        if body and body[0].get("role") != "user":
            body = body[1:]
    return head + body


def sanitize_chat_messages(raw: Any, fallback_text: str = "") -> list[dict[str, str]]:
    """整理解析对话历史，旧解析自动补一条 assistant 正文。"""
    messages: list[dict[str, str]] = []
    if isinstance(raw, list):
        for msg in raw:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "")
            content = str(msg.get("content") or "").strip()
            if role not in ("user", "assistant") or not content:
                continue
            entry = {"role": role, "content": content[:8000]}
            quote = str(msg.get("quote") or "").strip()
            if quote:
                entry["quote"] = quote[:500]
            messages.append(entry)
    if not messages:
        text = str(fallback_text or "").strip()
        if text:
            messages = [{"role": "assistant", "content": text[:8000]}]
    return trim_chat_messages(messages)


def default_recite_types() -> list[dict[str, str]]:
    """默认类型列表，每项含稳定 id、名称和提示词。"""
    return [
        {"id": uuid.uuid4().hex, "name": name, "prompt": DEFAULT_TYPE_PROMPTS[name]}
        for name in DEFAULT_RECITE_TYPES
    ]

# DeepSeek AI 默认设置。apiKey 默认空，由用户在设置面板填写。
DEFAULT_AI_SETTINGS: dict[str, Any] = {
    "apiKey": "",
    "baseUrl": "https://api.deepseek.com",
    "model": "deepseek-flash",
    "temperature": 1.0,
    "topP": 1.0,
    "maxTokens": 2048,
    "thinking": True,
    "reasoningEffort": "high",
    "webSearch": False,
    "systemPrompt": "你是一位耐心、简洁的背诵助手。回答准确、条理清晰，尽量简短。",
    "autoAnalyze": False,
}


# ------------------------------------------------------------------
# 二、日期与校验工具
# ------------------------------------------------------------------
def today_date() -> date:
    """本机当前日期。单独封装，方便测试时替换。"""
    return date.today()


def parse_iso_date(value: Any) -> date | None:
    """把 '2026-10-25' 安全地转成 date。"""
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def validate_review_intervals(
    values: Any,
    *,
    min_nodes: int = MIN_INTERVAL_NODE_COUNT,
    max_nodes: int = MAX_INTERVAL_NODE_COUNT,
) -> tuple[list[int] | None, str]:
    """校验复习节点，返回 (整数列表, 错误文案)；错误文案为空表示通过。"""
    if not isinstance(values, (list, tuple)):
        return None, "复习节点必须是数字列表"
    if len(values) < min_nodes:
        return None, f"至少需要 {min_nodes} 个复习节点"
    if len(values) > max_nodes:
        return None, f"最多支持 {max_nodes} 个复习节点"

    numbers: list[int] = []
    for raw_value in values:
        if isinstance(raw_value, bool):
            return None, "复习节点必须是正整数"
        if isinstance(raw_value, int):
            number = raw_value
        elif isinstance(raw_value, str):
            text = raw_value.strip()
            if not text.isdecimal():
                return None, "复习节点必须是正整数"
            try:
                number = int(text)
            except ValueError:
                return None, "复习节点必须是正整数"
        else:
            return None, "复习节点必须是正整数"

        if number < 1 or number > MAX_INTERVAL_DAY:
            return None, f"复习节点应在 1 ~ {MAX_INTERVAL_DAY} 天之间"
        numbers.append(number)

    if len(set(numbers)) != len(numbers):
        return None, "复习节点不能重复"
    for previous, current in zip(numbers, numbers[1:]):
        if current <= previous:
            return None, "复习节点必须从小到大排列"
    return numbers, ""


def next_ebbinghaus_day(days: list[int] | tuple[int, ...]) -> int:
    """以当前最大节点为基准，返回遗忘曲线上第一个更大的节点。"""
    last = max((day for day in days if isinstance(day, int)), default=0)
    for value in EBBINGHAUS_INTERVALS:
        if value > last:
            return value
    return min(max(last * 2, last + 1), MAX_INTERVAL_DAY)


def format_interval_summary(intervals: list[int] | tuple[int, ...]) -> str:
    """[1, 3, 7] -> '1 / 3 / 7'。"""
    return " / ".join(str(day) for day in intervals)


def format_cn_date(value: date) -> str:
    return f"{value.year}年{value.month}月{value.day}日"


def format_month_day(value: date) -> str:
    return f"{value.month}月{value.day}日"


def format_timeline_date(value: date) -> str:
    return f"{value.year}.{value.month:02d}.{value.day:02d}"


def format_created_at(value: Any) -> str:
    try:
        dt = datetime.fromisoformat(str(value))
        return f"创建于 {dt.year}年{dt.month}月{dt.day}日"
    except (TypeError, ValueError):
        return "创建时间未知"


def clean_type_name(value: Any) -> str:
    return str(value or "").strip()[:MAX_RECITE_TYPE_NAME]


def normalize_recite_type(raw_type: Any, raw_custom: Any = None) -> str | None:
    """整理单个条目的背诵类型。

    旧版用「其他 + 自拟名称」表示自定义类型，迁移时直接取自拟名称。
    """
    value = str(raw_type or "").strip()
    custom = str(raw_custom or "").strip()
    if value == "其他" and custom:
        value = custom
    value = value[:MAX_RECITE_TYPE_NAME]
    return value or None


def recite_type_label(item: dict[str, Any]) -> str:
    """卡片上显示的类型文字。"""
    return normalize_recite_type(item.get("type"), item.get("customType")) or DEFAULT_RECITE_TYPE


def validate_recite_types(raw: Any) -> tuple[list[dict[str, str]] | None, str]:
    """校验用户维护的类型列表，返回 (规范化列表, 错误文案)。"""
    if not isinstance(raw, list):
        return None, "背诵类型格式不正确"

    result: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = clean_type_name(entry.get("name"))
        if not name:
            return None, "类型名称不能为空"
        if name in seen_names:
            return None, f"类型「{name}」重复了，请换一个名称"
        seen_names.add(name)

        type_id = str(entry.get("id") or "").strip()
        if not type_id or type_id in seen_ids:
            type_id = uuid.uuid4().hex
        seen_ids.add(type_id)

        prompt = str(entry.get("prompt") or "").strip()[:MAX_TYPE_PROMPT_LENGTH]
        result.append({"id": type_id, "name": name, "prompt": prompt})

    if not result:
        return None, "至少保留一个背诵类型"
    if len(result) > 30:
        return None, "背诵类型最多 30 个"
    return result, ""


def normalize_ai_settings(raw: Any) -> dict[str, Any]:
    """整理 AI 设置，非法值回退到默认值。"""
    settings = copy.deepcopy(DEFAULT_AI_SETTINGS)
    if not isinstance(raw, dict):
        return settings

    for key in ("apiKey", "baseUrl", "model", "systemPrompt"):
        if key in raw:
            settings[key] = str(raw.get(key) or "")
    if not settings["baseUrl"].strip():
        settings["baseUrl"] = DEFAULT_AI_SETTINGS["baseUrl"]
    if not settings["model"].strip():
        settings["model"] = DEFAULT_AI_SETTINGS["model"]
    settings["systemPrompt"] = settings["systemPrompt"][:2000]

    def number(key: str, low: float, high: float, as_int: bool = False) -> None:
        try:
            value = float(raw.get(key, settings[key]))
        except (TypeError, ValueError):
            return
        value = max(low, min(high, value))
        settings[key] = int(value) if as_int else round(value, 2)

    number("temperature", 0.0, 2.0)
    number("topP", 0.0, 1.0)
    number("maxTokens", 256.0, 32768.0, as_int=True)

    for key in ("thinking", "webSearch", "autoAnalyze"):
        if key in raw:
            settings[key] = bool(raw.get(key))

    effort = str(raw.get("reasoningEffort", "")).strip().lower()
    if effort in ("low", "high", "max"):
        settings["reasoningEffort"] = effort
    return settings


# ------------------------------------------------------------------
# 三、数据读写
# ------------------------------------------------------------------
def default_data() -> dict[str, Any]:
    return {
        "version": 1,
        "settings": {
            "appearance": "system",
            # 旧版全局字段仅作兼容保留，新版每条内容用自己的 interval_days。
            "review_intervals": list(DEFAULT_REVIEW_INTERVALS),
            # AI 设置（含 API Key）保存在本地数据文件里，请勿分享该文件。
            "ai": copy.deepcopy(DEFAULT_AI_SETTINGS),
            # 用户自定义的背诵类型与各类型解析提示词。
            "recite_types": default_recite_types(),
        },
        "items": [],
    }


def normalize_data(raw: Any) -> dict[str, Any]:
    """整理手改过或旧版本的 JSON，尽量保住可用条目，跳过坏条目。"""
    if not isinstance(raw, dict):
        return default_data()

    data = default_data()

    settings = raw.get("settings")
    if isinstance(settings, dict):
        appearance = settings.get("appearance", "system")
        if appearance in APPEARANCE_MODES.values():
            data["settings"]["appearance"] = appearance
        intervals, _error = validate_review_intervals(settings.get("review_intervals"))
        if intervals is not None:
            data["settings"]["review_intervals"] = intervals
        data["settings"]["ai"] = normalize_ai_settings(settings.get("ai"))

    def finalize_types() -> None:
        """确定类型列表：新格式直接校验；旧格式从 typePrompts 迁移并补齐已用类型。"""
        raw_types = settings.get("recite_types") if isinstance(settings, dict) else None
        types, _type_error = validate_recite_types(raw_types)
        migrated = types is None

        old_prompts: dict[str, str] = {}
        if isinstance(settings, dict):
            old_ai = settings.get("ai")
            if isinstance(old_ai, dict) and isinstance(old_ai.get("typePrompts"), dict):
                old_prompts = {
                    str(key): str(value)
                    for key, value in old_ai["typePrompts"].items()
                    if isinstance(value, str)
                }

        if migrated:
            types = default_recite_types()
            for entry in types:
                saved = old_prompts.get(entry["name"], "").strip()
                if saved:
                    entry["prompt"] = saved[:MAX_TYPE_PROMPT_LENGTH]

            known = {entry["name"] for entry in types}
            fallback = (old_prompts.get("其他") or GENERIC_TYPE_PROMPT)[:MAX_TYPE_PROMPT_LENGTH]
            for item in data["items"]:
                name = item["type"]
                if name not in known:
                    types.append({"id": uuid.uuid4().hex, "name": name, "prompt": fallback})
                    known.add(name)

        data["settings"]["recite_types"] = types

    raw_items = raw.get("items")
    if not isinstance(raw_items, list):
        finalize_types()
        return data

    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        title = str(raw_item.get("title", "")).strip()
        if not title:
            continue

        item_id = str(raw_item.get("id", "")).strip() or uuid.uuid4().hex
        note = str(raw_item.get("note", "") or "")
        created_at = str(raw_item.get("created_at", "") or "")

        reviews: list[dict[str, Any]] = []
        seen_days: set[int] = set()
        raw_reviews = raw_item.get("reviews")
        if isinstance(raw_reviews, list):
            for raw_review in raw_reviews:
                if not isinstance(raw_review, dict):
                    continue
                raw_day = raw_review.get("day")
                if isinstance(raw_day, bool):
                    continue
                if isinstance(raw_day, int):
                    day = raw_day
                elif isinstance(raw_day, str) and raw_day.strip().isdigit():
                    day = int(raw_day.strip())
                else:
                    continue
                if day < 1 or day > MAX_INTERVAL_DAY or day in seen_days:
                    continue
                due = parse_iso_date(raw_review.get("date"))
                if due is None:
                    continue

                done = bool(raw_review.get("done", False))
                completed_at = raw_review.get("completed_at")
                if not done:
                    completed_at = None
                reviews.append({
                    "day": day,
                    "date": due.isoformat(),
                    "done": done,
                    "completed_at": completed_at,
                })
                seen_days.add(day)

        if not reviews:
            continue
        reviews.sort(key=lambda review: review["day"])

        review_days = [review["day"] for review in reviews]
        stored_intervals, _error = validate_review_intervals(raw_item.get("interval_days"))
        if stored_intervals and set(stored_intervals) == set(review_days):
            interval_days = stored_intervals
        else:
            interval_days = review_days

        # 旧数据没有 type 字段，统一迁移为「诗词」；「其他 + 自拟名称」取名称。
        recite_type = normalize_recite_type(
            raw_item.get("type"), raw_item.get("customType")
        ) or DEFAULT_RECITE_TYPE

        analysis = None
        raw_analysis = raw_item.get("analysis")
        if isinstance(raw_analysis, dict):
            analysis_text = str(raw_analysis.get("text", "") or "").strip()
            if analysis_text:
                analysis = {
                    "text": analysis_text[:8000],
                    "model": str(raw_analysis.get("model", "") or ""),
                    "createdAt": str(raw_analysis.get("createdAt", "") or ""),
                    "messages": sanitize_chat_messages(
                        raw_analysis.get("messages"), analysis_text
                    ),
                }

        data["items"].append({
            "id": item_id,
            "title": title,
            "note": note,
            "type": recite_type,
            "created_at": created_at,
            "interval_days": interval_days,
            "reviews": reviews,
            "analysis": analysis,
        })

    finalize_types()
    return data


class DataStore:
    """负责 JSON 文件的读取、损坏备份与原子保存。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.last_error = ""
        self.load_warning = ""

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return default_data()
        try:
            with self.path.open("r", encoding="utf-8") as file:
                raw = json.load(file)
            return normalize_data(raw)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            backup_name = self._backup_corrupt_file()
            if backup_name:
                detail = f"原文件已备份为：{backup_name}"
            else:
                detail = f"原文件已保留：{self.path.name}"
            self.load_warning = f"数据文件读取失败，已使用空数据启动。{detail}"
            self.last_error = str(exc)
            return default_data()

    def _backup_corrupt_file(self) -> str | None:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = self.path.with_name(
            f"{self.path.stem}.corrupt-{timestamp}{self.path.suffix}"
        )
        try:
            self.path.replace(backup_path)
            return backup_path.name
        except OSError:
            return None

    def save(self, data: dict[str, Any]) -> bool:
        """先写 .tmp，再 os.replace 整体替换，避免写出半个 JSON。"""
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            json_text = json.dumps(data, ensure_ascii=False, indent=2)
            with tmp_path.open("w", encoding="utf-8", newline="\n") as file:
                file.write(json_text)
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp_path, self.path)
            self.last_error = ""
            return True
        except OSError as exc:
            self.last_error = str(exc)
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            return False


# ------------------------------------------------------------------
# 四、业务核心
# ------------------------------------------------------------------
def ok(message: str = "", **extra: Any) -> dict[str, Any]:
    return {"ok": True, "message": message, "kind": "success", **extra}


def fail(message: str, kind: str = "error", **extra: Any) -> dict[str, Any]:
    return {"ok": False, "message": message, "kind": kind, **extra}


class ReviewCore:
    """所有业务操作的唯一入口，WebView2 的 JS API 只是它的薄封装。"""

    def __init__(self, path: Path | None = None) -> None:
        self.store = DataStore(path or DATA_FILE)
        self.data = self.store.load()
        self.save_text = "●  数据已就绪"
        self.save_ok = True

    # ---------------- 数据查询 ----------------
    def item_interval_days(self, item: dict[str, Any]) -> list[int]:
        review_days = sorted({
            int(review["day"])
            for review in item.get("reviews", [])
            if isinstance(review.get("day"), int)
            and 1 <= int(review["day"]) <= MAX_INTERVAL_DAY
        })
        intervals, _error = validate_review_intervals(item.get("interval_days"))
        if intervals and set(intervals) == set(review_days):
            return intervals
        return review_days or list(DEFAULT_REVIEW_INTERVALS)

    def item_base_day(self, item: dict[str, Any]) -> date:
        """找这条内容“第 1 天”对应的日期。"""
        try:
            return datetime.fromisoformat(str(item.get("created_at", ""))).date()
        except (TypeError, ValueError):
            candidates: list[tuple[int, date]] = []
            for review in item.get("reviews", []):
                day = review.get("day")
                due = parse_iso_date(review.get("date"))
                if isinstance(day, int) and due is not None:
                    candidates.append((day, due))
            if candidates:
                first_day, first_due = min(candidates, key=lambda row: row[0])
                return first_due - timedelta(days=first_day - 1)
            return today_date()

    def pending_tasks(self) -> list[tuple[dict[str, Any], dict[str, Any], date]]:
        """未完成且到期日 <= 今天，按到期日 / 添加时间 / 标题升序。"""
        now = today_date()
        tasks: list[tuple[dict[str, Any], dict[str, Any], date]] = []
        for item in self.data["items"]:
            for review in item.get("reviews", []):
                if review.get("done"):
                    continue
                due = parse_iso_date(review.get("date"))
                if due is None or due > now:
                    continue
                tasks.append((item, review, due))
        tasks.sort(key=lambda row: (
            row[2], str(row[0].get("created_at", "")), row[0]["title"]
        ))
        return tasks

    def completed_today_count(self) -> int:
        today_iso = today_date().isoformat()
        return sum(
            1
            for item in self.data["items"]
            for review in item.get("reviews", [])
            if review.get("done")
            and str(review.get("completed_at", "") or "").startswith(today_iso)
        )

    def item_done_count(self, item: dict[str, Any]) -> int:
        return sum(1 for review in item.get("reviews", []) if review.get("done"))

    def item_all_done(self, item: dict[str, Any]) -> bool:
        total = len(self.item_interval_days(item))
        return total > 0 and self.item_done_count(item) >= total

    def find_item(self, item_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self.data["items"] if item["id"] == item_id),
            None,
        )

    # ---------------- 视图模型 ----------------
    def state(self) -> dict[str, Any]:
        """一次性返回前端渲染所需的全部数据，避免前端重复实现业务规则。"""
        today = today_date()
        pending = self.pending_tasks()
        completed = self.completed_today_count()
        total = len(pending) + completed
        percent = int(round(completed / total * 100)) if total else 0

        if total == 0:
            detail = "今天暂无复习安排"
        elif not pending:
            detail = "今日任务全部完成"
        else:
            detail = f"还有 {len(pending)} 项待完成"

        pending_view: list[dict[str, Any]] = []
        for item, review, due in pending:
            overdue_days = (today - due).days
            pending_view.append({
                "itemId": item["id"],
                "reviewIndex": item["reviews"].index(review),
                "day": review["day"],
                "date": review["date"],
                "title": item["title"],
                "note": str(item.get("note", "") or ""),
                "type": recite_type_label(item),
                "createdText": format_created_at(item.get("created_at")),
                "overdueDays": overdue_days,
                "dueText": "今天到期" if overdue_days == 0 else f"已逾期 {overdue_days} 天",
                "analysis": item.get("analysis"),
            })

        plans_view: list[dict[str, Any]] = []
        finished_count = 0
        for item in sorted(
            self.data["items"],
            key=lambda row: str(row.get("created_at", "")),
            reverse=True,
        ):
            intervals = self.item_interval_days(item)
            done_count = self.item_done_count(item)
            all_done = self.item_all_done(item)
            if all_done:
                finished_count += 1

            nodes: list[dict[str, Any]] = []
            for review in item.get("reviews", []):
                due = parse_iso_date(review.get("date"))
                if review.get("done"):
                    status, status_text = "done", "✓ 已完成"
                elif due is None:
                    status, status_text = "future", "待复习"
                elif due < today:
                    status = "overdue"
                    status_text = f"逾期 {(today - due).days} 天"
                elif due == today:
                    status, status_text = "today", "今天"
                else:
                    status, status_text = "future", "待复习"
                nodes.append({
                    "day": review["day"],
                    "date": review["date"],
                    "dateText": format_timeline_date(due) if due else "日期未知",
                    "status": status,
                    "statusText": status_text,
                })

            plans_view.append({
                "id": item["id"],
                "title": item["title"],
                "note": str(item.get("note", "") or ""),
                "type": recite_type_label(item),
                "reciteType": recite_type_label(item),
                "analysis": item.get("analysis"),
                "createdText": format_created_at(item.get("created_at")),
                "intervals": intervals,
                "intervalText": format_interval_summary(intervals),
                "baseDay": self.item_base_day(item).isoformat(),
                "total": len(intervals),
                "done": done_count,
                "allDone": all_done,
                "nodes": nodes,
                "meta": (
                    f"{format_created_at(item.get('created_at'))}  ·  "
                    f"共 {len(intervals)} 个复习节点  ·  "
                    f"时间轴 {format_interval_summary(intervals)} 天"
                ),
            })

        appearance = self.data.get("settings", {}).get("appearance", "system")
        if appearance not in APPEARANCE_LABELS:
            appearance = "system"

        return {
            "appName": APP_NAME,
            "version": APP_VERSION,
            "appearance": appearance,
            "appearanceLabel": APPEARANCE_LABELS[appearance],
            "saveStatus": {"ok": self.save_ok, "text": self.save_text},
            "loadWarning": self.store.load_warning,
            "today": {
                "iso": today.isoformat(),
                "cn": format_cn_date(today),
                "monthDay": format_month_day(today),
                "weekday": WEEKDAYS_CN[today.weekday()],
            },
            "stats": {
                "pending": len(pending),
                "completed": completed,
                "total": total,
                "percent": percent,
                "detail": detail,
            },
            "pending": pending_view,
            "plans": plans_view,
            "planStats": {
                "total": len(plans_view),
                "ongoing": len(plans_view) - finished_count,
                "finished": finished_count,
            },
            "defaults": {
                "intervals": list(DEFAULT_REVIEW_INTERVALS),
                "maxNodes": MAX_INTERVAL_NODE_COUNT,
                "minNodes": MIN_INTERVAL_NODE_COUNT,
                "nextDay": next_ebbinghaus_day(DEFAULT_REVIEW_INTERVALS),
            },
            "types": [
                entry["name"]
                for entry in self.data["settings"]["recite_types"]
            ],
            "aiConfigured": bool(
                self.data.get("settings", {}).get("ai", {}).get("apiKey", "").strip()
            ),
            "autoAnalyze": bool(
                self.data.get("settings", {}).get("ai", {}).get("autoAnalyze", False)
            ),
        }

    # ---------------- 保存 ----------------
    def _save_data(self) -> bool:
        success = self.store.save(self.data)
        if success:
            self.save_text = f"●  已自动保存 {datetime.now().strftime('%H:%M')}"
            self.save_ok = True
        else:
            self.save_text = "●  保存失败"
            self.save_ok = False
        return success

    # ---------------- 业务操作 ----------------
    def type_names(self) -> list[str]:
        entries = self.data.get("settings", {}).get("recite_types") or default_recite_types()
        return [entry["name"] for entry in entries]

    def type_prompt(self, name: str) -> str:
        """取某个类型的解析提示词，没有配置时用通用模板。"""
        entries = self.data.get("settings", {}).get("recite_types") or []
        for entry in entries:
            if entry.get("name") == name:
                return str(entry.get("prompt") or "").strip() or GENERIC_TYPE_PROMPT
        return GENERIC_TYPE_PROMPT

    def _resolve_type(self, raw_type: Any, raw_custom: Any = None) -> str:
        """把界面传来的类型落到已配置的类型上，非法值回退到第一个类型。"""
        names = self.type_names()
        value = normalize_recite_type(raw_type, raw_custom)
        if value in names:
            return value
        return names[0] if names else DEFAULT_RECITE_TYPE

    def add_item(
        self,
        title: Any,
        note: Any,
        intervals: Any,
        recite_type: Any = None,
        custom_type: Any = None,
    ) -> dict[str, Any]:
        clean_title = str(title or "").strip()
        if not clean_title:
            return fail("请先填写背诵内容标题")
        if len(clean_title) > MAX_TITLE_LENGTH:
            return fail(f"标题过长，请控制在 {MAX_TITLE_LENGTH} 个字符以内")
        clean_note = str(note or "")
        if len(clean_note) > MAX_NOTE_LENGTH:
            return fail(f"备注过长，请控制在 {MAX_NOTE_LENGTH} 个字符以内")

        validated, error = validate_review_intervals(intervals)
        if validated is None:
            return fail(error)

        now = datetime.now().astimezone()
        base_day = today_date()
        reviews = [{
            "day": day,
            "date": (base_day + timedelta(days=day - 1)).isoformat(),
            "done": False,
            "completed_at": None,
        } for day in validated]

        chosen_type = self._resolve_type(recite_type, custom_type)
        item = {
            "id": uuid.uuid4().hex,
            "title": clean_title,
            "note": clean_note,
            "type": chosen_type,
            "created_at": now.isoformat(timespec="seconds"),
            "interval_days": validated,
            "reviews": reviews,
            "analysis": None,
        }
        self.data["items"].insert(0, item)
        if not self._save_data():
            self.data["items"].remove(item)
            return fail("保存失败，请检查目录是否可写")

        return ok(
            f"已为「{clean_title}」生成 {len(validated)} 个复习节点",
            view="today",
            itemId=item["id"],
        )

    def update_item(
        self,
        item_id: str,
        title: Any,
        note: Any,
        recite_type: Any = None,
        custom_type: Any = None,
    ) -> dict[str, Any]:
        item = self.find_item(item_id)
        if item is None:
            return fail("这条内容已经不存在，请刷新后重试")

        clean_title = str(title or "").strip()
        if not clean_title:
            return fail("请先填写背诵内容标题")
        if len(clean_title) > MAX_TITLE_LENGTH:
            return fail(f"标题过长，请控制在 {MAX_TITLE_LENGTH} 个字符以内")
        clean_note = str(note or "")
        if len(clean_note) > MAX_NOTE_LENGTH:
            return fail(f"备注过长，请控制在 {MAX_NOTE_LENGTH} 个字符以内")

        old_title = item.get("title", "")
        old_note = item.get("note", "")
        old_type = item.get("type")
        old_custom = item.pop("customType", None)
        item["title"] = clean_title
        item["note"] = clean_note
        if recite_type is not None:
            item["type"] = self._resolve_type(recite_type, custom_type)
        if not self._save_data():
            item["title"] = old_title
            item["note"] = old_note
            item["type"] = old_type
            if old_custom is not None:
                item["customType"] = old_custom
            return fail("保存失败，请检查目录是否可写")

        return ok(f"「{clean_title}」的内容已更新")

    def save_intervals(self, item_id: str, intervals: Any) -> dict[str, Any]:
        validated, error = validate_review_intervals(intervals)
        if validated is None:
            return fail(error)

        item = self.find_item(item_id)
        if item is None:
            return fail("这条内容已经不存在，请刷新后重试")

        base_day = self.item_base_day(item)
        old_reviews = item.get("reviews", [])
        old_interval_days = item.get("interval_days")
        old_by_day = {
            review["day"]: review
            for review in old_reviews
            if isinstance(review.get("day"), int)
        }

        new_reviews: list[dict[str, Any]] = []
        for day in validated:
            old_review = old_by_day.get(day)
            done = bool(old_review and old_review.get("done"))
            new_reviews.append({
                "day": day,
                "date": (base_day + timedelta(days=day - 1)).isoformat(),
                "done": done,
                "completed_at": old_review.get("completed_at") if done else None,
            })

        item["interval_days"] = list(validated)
        item["reviews"] = new_reviews
        if not self._save_data():
            item["interval_days"] = old_interval_days
            item["reviews"] = old_reviews
            return fail("时间轴保存失败，请检查目录是否可写")

        title = item["title"]
        return ok(
            f"「{title}」的时间轴已更新为 第 {format_interval_summary(validated)} 天"
        )

    def complete_review(self, item_id: str, due_iso: str) -> dict[str, Any]:
        """按 item_id + 到期日期匹配节点（与旧版一致）。"""
        target_item: dict[str, Any] | None = None
        target_review: dict[str, Any] | None = None
        for item in self.data["items"]:
            if item["id"] != item_id:
                continue
            for review in item["reviews"]:
                if review["date"] == due_iso:
                    target_item, target_review = item, review
                    break
            break

        if target_item is None or target_review is None or target_review.get("done"):
            return ok()

        target_review["done"] = True
        target_review["completed_at"] = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        if not self._save_data():
            target_review["done"] = False
            target_review["completed_at"] = None
            return fail("保存失败，本次完成状态未记录")

        title = target_item["title"]
        done_count = self.item_done_count(target_item)
        total_nodes = len(self.item_interval_days(target_item))
        if done_count >= total_nodes:
            message = f"「{title}」的 {total_nodes} 次复习全部完成！"
        else:
            next_review = next(
                (
                    review
                    for review in sorted(
                        target_item["reviews"], key=lambda row: row["day"]
                    )
                    if not review.get("done")
                ),
                None,
            )
            if next_review:
                next_date = parse_iso_date(next_review["date"])
                if next_date and next_date < today_date():
                    message = (
                        f"已完成「{title}」第 {target_review['day']} 天复习，"
                        "还有逾期节点待补"
                    )
                elif next_date == today_date():
                    message = (
                        f"已完成「{title}」第 {target_review['day']} 天复习，"
                        "今天还有节点待完成"
                    )
                else:
                    next_text = format_month_day(next_date) if next_date else "稍后"
                    message = (
                        f"已完成「{title}」第 {target_review['day']} 天复习，"
                        f"下次 {next_text}"
                    )
            else:
                message = f"已完成「{title}」的复习"

        return ok(message)

    def delete_item(self, item_id: str) -> dict[str, Any]:
        index = next(
            (
                i
                for i, item in enumerate(self.data["items"])
                if item["id"] == item_id
            ),
            None,
        )
        if index is None:
            return ok()

        removed = self.data["items"].pop(index)
        if not self._save_data():
            self.data["items"].insert(index, removed)
            return fail("删除失败，请检查目录是否可写")

        return ok(f"已删除「{removed['title']}」", kind="warning")

    def set_appearance(self, mode: str) -> dict[str, Any]:
        normalized = APPEARANCE_MODES.get(str(mode), str(mode))
        if normalized not in APPEARANCE_LABELS:
            normalized = "system"
        self.data.setdefault("settings", {})["appearance"] = normalized
        if not self._save_data():
            return fail("外观设置保存失败，请检查目录是否可写")
        return ok()

    # ---------------- 背诵类型管理 ----------------
    def get_recite_types(self) -> dict[str, Any]:
        types, _error = validate_recite_types(
            self.data.get("settings", {}).get("recite_types")
        )
        if types is None:
            types = default_recite_types()
            self.data.setdefault("settings", {})["recite_types"] = types
        return {"ok": True, "types": copy.deepcopy(types)}

    def save_recite_types(self, raw: Any) -> dict[str, Any]:
        """保存类型列表：支持增删改，改名会同步到已有内容。"""
        types, error = validate_recite_types(raw)
        if types is None:
            return fail(error)

        settings = self.data.setdefault("settings", {})
        old_types = settings.get("recite_types") or default_recite_types()
        old_by_id = {entry["id"]: entry["name"] for entry in old_types}
        new_by_id = {entry["id"]: entry["name"] for entry in types}

        removed_names = {
            name for type_id, name in old_by_id.items() if type_id not in new_by_id
        }
        if removed_names:
            counts: dict[str, int] = {}
            for item in self.data["items"]:
                name = recite_type_label(item)
                if name in removed_names:
                    counts[name] = counts.get(name, 0) + 1
            if counts:
                name, count = next(iter(counts.items()))
                return fail(
                    f"「{name}」下还有 {count} 条背诵内容，请先改掉这些内容的类型再删除"
                )

        renames = {
            old_by_id[type_id]: new_by_id[type_id]
            for type_id in old_by_id.keys() & new_by_id.keys()
            if old_by_id[type_id] != new_by_id[type_id]
        }
        old_item_types = [(item, item.get("type")) for item in self.data["items"]]
        for item, name in old_item_types:
            if name in renames:
                item["type"] = renames[name]

        settings["recite_types"] = types
        if not self._save_data():
            settings["recite_types"] = old_types
            for item, name in old_item_types:
                item["type"] = name
            return fail("类型设置保存失败，请检查目录是否可写")
        return ok("背诵类型已更新")

    # ---------------- AI 设置与解析缓存 ----------------
    def get_ai_settings(self) -> dict[str, Any]:
        """返回完整 AI 设置（含 API Key），只供设置面板调用。"""
        settings = self.data.setdefault("settings", {})
        settings["ai"] = normalize_ai_settings(settings.get("ai"))
        types, _error = validate_recite_types(settings.get("recite_types"))
        if types is None:
            types = default_recite_types()
            settings["recite_types"] = types
        return {
            "ok": True,
            "settings": copy.deepcopy(settings["ai"]),
            "reciteTypes": copy.deepcopy(types),
        }

    def save_ai_settings(self, raw: Any) -> dict[str, Any]:
        normalized = normalize_ai_settings(raw)
        settings = self.data.setdefault("settings", {})
        old = settings.get("ai")
        settings["ai"] = normalized
        if not self._save_data():
            settings["ai"] = old
            return fail("AI 设置保存失败，请检查目录是否可写")
        return ok("AI 设置已保存")

    def save_analysis(self, item_id: str, text: Any, model: str = "") -> dict[str, Any]:
        """把 AI 解析结果缓存到对应条目，避免每次打开都重新调用接口。"""
        item = self.find_item(item_id)
        if item is None:
            return fail("这条内容已经不存在，请刷新后重试")
        clean_text = str(text or "").strip()
        if not clean_text:
            return fail("AI 没有返回解析内容")

        old_analysis = item.get("analysis")
        item["analysis"] = {
            "text": clean_text[:8000],
            "model": str(model or ""),
            "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "messages": [{"role": "assistant", "content": clean_text[:8000]}],
        }
        if not self._save_data():
            item["analysis"] = old_analysis
            return fail("解析结果保存失败，请检查目录是否可写")
        return ok("AI 解析已保存")

    def delete_chat_message(self, item_id: str, index: int) -> dict[str, Any]:
        """删除某条自己的消息及其紧随的 AI 回复，保留其余对话。"""
        item = self.find_item(item_id)
        if item is None:
            return fail("这条内容已经不存在，请刷新后重试")
        analysis = item.get("analysis")
        if not isinstance(analysis, dict):
            return fail("请先生成 AI 解析")
        messages = analysis.get("messages") or []
        try:
            idx = int(index)
        except (TypeError, ValueError):
            return fail("消息序号无效")
        if idx < 0 or idx >= len(messages):
            return fail("这条消息已经不存在")
        if messages[idx].get("role") != "user":
            return fail("只能删除自己的消息")

        end = idx + 1
        if end < len(messages) and messages[end].get("role") == "assistant":
            end += 1
        remaining = list(messages[:idx]) + list(messages[end:])
        remaining = sanitize_chat_messages(remaining, analysis.get("text", ""))

        old_analysis = copy.deepcopy(analysis)
        analysis["messages"] = remaining
        if not self._save_data():
            item["analysis"] = old_analysis
            return fail("删除失败，请检查目录是否可写")
        return ok("已删除这条消息")

    def save_chat_messages(
        self,
        item_id: str,
        messages: Any,
        text: str | None = None,
    ) -> dict[str, Any]:
        """整段替换解析对话历史；编辑/重新生成会截断后续消息后调用。"""
        item = self.find_item(item_id)
        if item is None:
            return fail("这条内容已经不存在，请刷新后重试")
        analysis = item.get("analysis")
        if not isinstance(analysis, dict):
            return fail("请先生成 AI 解析")

        clean_messages = sanitize_chat_messages(messages, analysis.get("text", ""))
        old_analysis = copy.deepcopy(analysis)
        analysis["messages"] = clean_messages
        if text is not None:
            analysis["text"] = str(text)[:8000]
        if not self._save_data():
            item["analysis"] = old_analysis
            return fail("对话内容保存失败，请检查目录是否可写")
        return ok("对话已更新")

    def append_chat(
        self,
        item_id: str,
        question: Any,
        answer: Any,
        quote: Any = "",
    ) -> dict[str, Any]:
        """把一轮追问与回复追加到解析对话历史里。"""
        item = self.find_item(item_id)
        if item is None:
            return fail("这条内容已经不存在，请刷新后重试")
        analysis = item.get("analysis")
        if not isinstance(analysis, dict):
            return fail("请先生成 AI 解析再追问")

        clean_question = str(question or "").strip()
        clean_answer = str(answer or "").strip()
        if not clean_question:
            return fail("请输入追问内容")
        if not clean_answer:
            return fail("AI 没有返回回复内容")

        messages = sanitize_chat_messages(
            analysis.get("messages"), analysis.get("text", "")
        )
        user_msg: dict[str, str] = {"role": "user", "content": clean_question[:2000]}
        clean_quote = str(quote or "").strip()
        if clean_quote:
            user_msg["quote"] = clean_quote[:500]
        messages.extend([user_msg, {"role": "assistant", "content": clean_answer[:8000]}])
        messages = trim_chat_messages(messages)

        old_analysis = copy.deepcopy(analysis)
        analysis["messages"] = messages
        if not self._save_data():
            item["analysis"] = old_analysis
            return fail("对话内容保存失败，请检查目录是否可写")
        return ok("回复已保存")

    def clear_analysis(self, item_id: str) -> dict[str, Any]:
        item = self.find_item(item_id)
        if item is None:
            return ok()
        old_analysis = item.get("analysis")
        item["analysis"] = None
        if not self._save_data():
            item["analysis"] = old_analysis
            return fail("清除失败，请检查目录是否可写")
        return ok("已清除解析缓存")

    def refresh(self) -> dict[str, Any]:
        """F5：强制重新取本机日期，让跨天场景自动刷新。"""
        return ok("已刷新今日任务")
