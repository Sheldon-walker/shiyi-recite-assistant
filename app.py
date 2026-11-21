# -*- coding: utf-8 -*-
"""
拾忆 · 艾宾浩斯背诵助手
======================

一个使用 customtkinter 编写的本地背诵提醒工具。

核心规则
--------
新增一项背诵内容后，程序会以“今天”作为第 1 天，默认自动生成 5 个复习节点：

    第 1 天  -> 今天
    第 2 天  -> 明天
    第 4 天  -> 今天 + 3 天
    第 7 天  -> 今天 + 6 天
    第 15 天 -> 今天 + 14 天

这些节点不是全局统一的：新增背诵时可以单独设置这一条内容的时间轴，
之后也可以在「全部计划」里点「时间轴」单独调整。每条内容都会把自己的
节点和日期保存下来，互不影响。

数据会保存在程序同目录下的 review_data.json 中，采用“先写临时文件，
再整体替换”的方式，避免程序意外关闭时把原 JSON 写坏。

打包成 exe 后，数据会保存在 exe 旁边（dist 文件夹内），而不是临时解压目录。

运行方式
--------
    python app.py

依赖：
    pip install customtkinter

作者备注
--------
代码按“常量/工具函数 -> 数据层 -> 通用弹窗 -> 主界面”的顺序组织，
每一步都写了中文注释，方便阅读和修改。
"""

# ============================================================
# 一、导入依赖
# ============================================================
# 这些全部来自 Python 标准库，不需要额外安装。
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import tkinter as tk

# customtkinter 是界面库，需要提前通过 pip 安装。
import customtkinter as ctk


# ============================================================
# 二、应用常量与配色
# ============================================================
APP_NAME = "拾忆 · 艾宾浩斯背诵助手"
APP_VERSION = "1.3.0"

# 程序是否运行在 PyInstaller 打包出来的 exe 中。
# 打包后 __file__ 会指向临时解压目录，不能再用它定位数据文件，
# 否则用户关闭软件后临时目录被清理，数据就丢了。
IS_FROZEN = bool(getattr(sys, "frozen", False))

# - 源码运行时：程序目录 = app.py 所在目录。
# - exe 运行时：程序目录 = exe 所在目录（通常是 dist）。
APP_DIR = (
    Path(sys.executable).resolve().parent
    if IS_FROZEN
    else Path(__file__).resolve().parent
)

# 图标等“只读资源”在 onefile exe 中会被解压到 sys._MEIPASS。
# 源码运行时资源目录和程序目录相同。
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))

# 数据永远写在“程序旁边”，这样用户能直接看到、备份和迁移。
DATA_FILE = APP_DIR / "review_data.json"
ICON_FILE = RESOURCE_DIR / "assets" / "app_icon.ico"

# 默认的艾宾浩斯复习时间轴（新建内容时的初始节点）。
# 这里的数字是“距添加当天的第几天”，不是两次复习之间的间隔：
# 第 1 天 = 添加当天，第 2 天 = 次日，以此类推。
DEFAULT_REVIEW_INTERVALS: tuple[int, ...] = (1, 2, 4, 7, 15)

# 艾宾浩斯曲线的参考节点。增加节点时按这个序列往后取第一个更大的值，
# 这样多出来的默认节点仍然沿着遗忘曲线走，而不是随手补一个数字。
EBBINGHAUS_INTERVALS: tuple[int, ...] = (
    1, 2, 4, 7, 15, 30, 60, 120, 240, 365, 730, 1095, 1825, 3650,
)

# 每条背诵的时间轴节点数量范围：至少 1 个；最多 10 个，
# 界面上每行 5 个，刚好排两行。
MIN_INTERVAL_NODE_COUNT = 1
MAX_INTERVAL_NODE_COUNT = 10

# 时间轴输入框每行放几个，节点变多时自动换到下一行。
TIMELINE_COLUMNS = 5

# 防止用户误输入过于离谱的日期，最大允许到第 3650 天（约 10 年）。
MAX_INTERVAL_DAY = 3650

# 界面字体。微软雅黑在 Windows 上显示中文比较舒服；
# 如果系统没有该字体，Tk 会自动回退到可用字体。
FONT_FAMILY = "Microsoft YaHei UI"

# 所有颜色都使用 (浅色模式, 深色模式) 的元组。
# customtkinter 会在外观模式切换时自动选择对应的颜色，
# 因此不需要手动遍历控件重新上色。
COLORS: dict[str, Any] = {
    "bg":           ("#F4F5F9", "#0F1117"),  # 窗口主背景
    "sidebar":      ("#FBFBFD", "#141821"),  # 左侧边栏
    "card":         ("#FFFFFF", "#1A1F2B"),  # 卡片
    "card_alt":     ("#F7F8FC", "#202633"),  # 次级卡片 / 输入框
    "border":       ("#E7E9F1", "#293140"),  # 描边
    "text":         ("#181B26", "#F2F4FA"),  # 主文字
    "muted":        ("#777F93", "#9AA3B7"),  # 次要文字
    "faint":        ("#A5ABBB", "#6E778C"),  # 更弱的说明文字
    "accent":       ("#5E54E8", "#7C70FF"),  # 品牌主色（填充）
    "accent_hover": ("#4D43D4", "#8D82FF"),  # 主色悬停
    "accent_text":  ("#554BD8", "#B8B1FF"),  # 主色文字
    "accent_soft":  ("#EEECFF", "#252343"),  # 主色浅底
    "track":        ("#E7E4FF", "#33314F"),  # 进度条轨道
    "green":        ("#16855F", "#57D6AA"),  # 成功文字
    "green_soft":   ("#E8F8F1", "#173A2F"),  # 成功浅底
    "orange":       ("#B46912", "#F3B75C"),  # 提醒 / 逾期文字
    "orange_soft":  ("#FFF3E2", "#3A2C19"),  # 提醒 / 逾期浅底
    "red":          ("#C7474F", "#FF7B84"),  # 危险操作
    "red_hover":    ("#A9363E", "#FF949B"),  # 危险操作悬停
    "red_soft":     ("#FCEBED", "#3A2226"),  # 危险操作浅底
    "white":        "#FFFFFF",                # 纯白，不随主题变化
}

# 下拉框中显示给用户的中文选项，以及 customtkinter 内部使用的值。
APPEARANCE_LABELS = {
    "system": "跟随系统",
    "light": "浅色",
    "dark": "深色",
}
APPEARANCE_MODES = {label: mode for mode, label in APPEARANCE_LABELS.items()}

# 中文星期，用于页头日期显示。date.weekday() 的 0 是星期一。
WEEKDAYS_CN = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


# ============================================================
# 三、小工具函数
# ============================================================
def ui_font(size: int, weight: str = "normal") -> tuple[str, int, str]:
    """返回 customtkinter 可以直接使用的字体元组，减少重复代码。"""
    return (FONT_FAMILY, size, weight)


def today_date() -> date:
    """获取本机当前日期。单独封装后，未来要做测试或调整时更方便。"""
    return date.today()


def parse_iso_date(value: Any) -> date | None:
    """把 "2026-10-25" 这样的字符串安全地转成 date 对象。"""
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
    """
    校验一组复习节点天数，返回 (校验后的整数列表, 错误提示)。

    合法条件：
    1. 必须是非空列表，节点数量在 min_nodes ~ max_nodes 之间；
    2. 每个值都是 1 ~ MAX_INTERVAL_DAY 的正整数；
    3. 必须严格从小到大，且不能重复。

    返回的错误字符串为空表示校验通过。
    """
    if not isinstance(values, (list, tuple)):
        return None, "复习节点必须是数字列表"

    if len(values) < min_nodes:
        return None, f"至少需要 {min_nodes} 个复习节点"
    if len(values) > max_nodes:
        return None, f"最多支持 {max_nodes} 个复习节点"
    if len(values) == 0:
        return None, "至少需要一个复习节点"

    numbers: list[int] = []
    for raw_value in values:
        # bool 是 int 的子类，要单独排除，避免 True 被当成 1。
        if isinstance(raw_value, bool):
            return None, "复习节点必须是正整数"
        if isinstance(raw_value, int):
            number = raw_value
        elif isinstance(raw_value, str):
            # isdecimal 比 isdigit 更严格；随后仍用 try 兜底，
            # 防止某些特殊 Unicode 数字让 int() 抛异常。
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
    """
    取艾宾浩斯曲线上的下一个复习节点。

    以当前最大的节点为基准，返回曲线序列里第一个更大的值；
    曲线用完后按翻倍递增，最多到 MAX_INTERVAL_DAY。
    """
    last = max((day for day in days if isinstance(day, int)), default=0)
    for value in EBBINGHAUS_INTERVALS:
        if value > last:
            return value
    return min(max(last * 2, last + 1), MAX_INTERVAL_DAY)


def format_interval_summary(intervals: list[int] | tuple[int, ...]) -> str:
    """把 [1, 3, 7] 格式化成适合界面显示的 “1 / 3 / 7”。"""
    return " / ".join(str(day) for day in intervals)


def format_cn_date(value: date) -> str:
    """完整中文日期，例如：2026年10月25日。"""
    return f"{value.year}年{value.month}月{value.day}日"


def format_month_day(value: date) -> str:
    """短日期，例如：10月25日。"""
    return f"{value.month}月{value.day}日"


def format_timeline_date(value: date) -> str:
    """时间轴上的日期。带年份，保证跨年时仍然清楚。"""
    return f"{value.year}.{value.month:02d}.{value.day:02d}"


def format_created_at(value: Any) -> str:
    """把保存的创建时间字符串转成中文展示；解析失败时给出兜底文案。"""
    try:
        dt = datetime.fromisoformat(str(value))
        return f"创建于 {dt.year}年{dt.month}月{dt.day}日"
    except (TypeError, ValueError):
        return "创建时间未知"


def make_badge(
    parent: tk.Misc,
    text: str,
    fg_color: Any,
    text_color: Any,
    size: int = 10,
) -> ctk.CTkFrame:
    """
    创建一个圆角小标签（胶囊样式）。

    CTkLabel 本身没有内边距参数，所以用一个透明容器包住 Label，
    再通过 pack 的 padx/pady 做出舒服的内边距。
    """
    badge = ctk.CTkFrame(parent, fg_color=fg_color, corner_radius=8)
    label = ctk.CTkLabel(
        badge,
        text=text,
        text_color=text_color,
        font=ui_font(size, "bold"),
        height=20,
    )
    label.pack(padx=8, pady=2)
    return badge


def bind_wraplength(
    container: tk.Misc,
    labels: list[ctk.CTkLabel],
    reserved_width: int = 0,
    minimum: int = 220,
) -> None:
    """
    让文字根据卡片宽度自动换行。

    Tk 的 wraplength 是固定像素值，窗口变窄时可能挤出卡片。
    这里监听容器的 <Configure> 事件，按当前宽度重新设置换行宽度。
    """
    state = {"last": 0}

    def _sync(event: tk.Event) -> None:
        # 预留右侧按钮/复选框的宽度，避免文字压到它们。
        usable = max(minimum, event.width - reserved_width)
        # 宽度变化不大时不重复设置，防止触发无意义的布局循环。
        if abs(usable - state["last"]) < 8:
            return
        state["last"] = usable
        for label in labels:
            try:
                label.configure(wraplength=usable)
            except tk.TclError:
                # 控件可能在事件触发后被销毁，忽略即可。
                pass

    container.bind("<Configure>", _sync, add="+")


def center_window(window: tk.Misc, width: int, height: int) -> None:
    """把窗口放到屏幕中央，并保证不会超出当前屏幕。"""
    screen_w = window.winfo_screenwidth()
    screen_h = window.winfo_screenheight()
    x = max(0, (screen_w - width) // 2)
    # 稍微向上偏一点，视觉上更居中，也给任务栏留空间。
    y = max(0, (screen_h - height) // 2 - 24)
    window.geometry(f"{width}x{height}+{x}+{y}")


# ============================================================
# 四、数据层：读写 JSON
# ============================================================
def default_data() -> dict[str, Any]:
    """返回一份全新的、结构完整的数据。"""
    return {
        "version": 1,
        "settings": {
            "appearance": "system",
            # 保留旧版本的全局字段，读取老数据时不会报错。
            # 新版本真正使用的是每条任务自己的 interval_days。
            "review_intervals": list(DEFAULT_REVIEW_INTERVALS),
        },
        "items": [],
    }


def normalize_data(raw: Any) -> dict[str, Any]:
    """
    把读到的 JSON 整理成程序期望的结构。

    即使 JSON 被人手动改过、字段缺失，也尽量让程序能继续打开，
    而不是直接崩溃。无法修复的条目会被跳过。
    """
    if not isinstance(raw, dict):
        return default_data()

    data = default_data()

    # 1. 读取外观设置，只接受程序支持的三种值。
    settings = raw.get("settings")
    if isinstance(settings, dict):
        appearance = settings.get("appearance", "system")
        if appearance in APPEARANCE_MODES.values():
            data["settings"]["appearance"] = appearance

        # 兼容旧版本：过去曾保存过全局 review_intervals。
        # 新版本以每条任务自己的 interval_days 为准，这里读取后仅作保留。
        # 如果字段缺失或被人为改坏，就保留 default_data 里的标准时间轴。
        intervals, _error = validate_review_intervals(
            settings.get("review_intervals"),
        )
        if intervals is not None:
            data["settings"]["review_intervals"] = intervals

    # 2. 逐条整理背诵内容。
    raw_items = raw.get("items")
    if not isinstance(raw_items, list):
        return data

    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue

        title = str(raw_item.get("title", "")).strip()
        if not title:
            # 没有标题的条目没有展示意义。
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

                # 兼容旧数据（整数 day）和手工修改过的数据（纯数字字符串）。
                raw_day = raw_review.get("day")
                if isinstance(raw_day, bool):
                    continue
                if isinstance(raw_day, int):
                    day = raw_day
                elif isinstance(raw_day, str) and raw_day.strip().isdigit():
                    day = int(raw_day.strip())
                else:
                    continue

                # 不再限定必须是 1/2/4/7/15，这样自定义时间轴的历史数据
                # 以及以后扩展的时间轴都能正常读取。
                if day < 1 or day > MAX_INTERVAL_DAY or day in seen_days:
                    continue
                due = parse_iso_date(raw_review.get("date"))
                if due is None:
                    continue

                done = bool(raw_review.get("done", False))
                completed_at = raw_review.get("completed_at")
                if not done:
                    completed_at = None

                reviews.append(
                    {
                        "day": day,
                        "date": due.isoformat(),
                        "done": done,
                        "completed_at": completed_at,
                    }
                )
                seen_days.add(day)

        # 一条正常的背诵内容至少要有复习节点。
        if not reviews:
            continue

        reviews.sort(key=lambda review: review["day"])

        # 每项内容都保存自己的时间轴。
        # 优先读取 interval_days；旧数据没有该字段时，直接从 reviews 推导，
        # 因此不同任务的时间轴互不影响。
        review_days = [review["day"] for review in reviews]
        stored_intervals, _error = validate_review_intervals(
            raw_item.get("interval_days"),
        )
        if stored_intervals and set(stored_intervals) == set(review_days):
            interval_days = stored_intervals
        else:
            interval_days = review_days

        data["items"].append(
            {
                "id": item_id,
                "title": title,
                "note": note,
                "created_at": created_at,
                "interval_days": interval_days,
                "reviews": reviews,
            }
        )

    return data


class DataStore:
    """
    专门负责“数据文件”的类。

    把读写逻辑从界面代码中拆出来有两个好处：
    1. 界面代码只需要调用 load / save，不必关心文件细节；
    2. 以后想换存储方式（例如 SQLite）时，只需改这个类。
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.last_error = ""
        self.load_warning = ""

    def load(self) -> dict[str, Any]:
        """读取本地 JSON；文件不存在时返回空数据。"""
        if not self.path.exists():
            return default_data()

        try:
            with self.path.open("r", encoding="utf-8") as file:
                raw = json.load(file)
            return normalize_data(raw)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            # 把损坏的文件改名保留下来，再以空数据启动。
            # 这样后续自动保存不会覆盖掉用户可能还想抢救的原始内容。
            backup_name = self._backup_corrupt_file()
            if backup_name:
                detail = f"原文件已备份为：{backup_name}"
            else:
                detail = f"原文件已保留：{self.path.name}"
            self.load_warning = f"数据文件读取失败，已使用空数据启动。{detail}"
            self.last_error = str(exc)
            return default_data()

    def _backup_corrupt_file(self) -> str | None:
        """将无法解析的 JSON 改名为带时间戳的备份文件，返回文件名。"""
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
        """
        原子化保存：
        1. 先把完整 JSON 写进临时文件；
        2. 确认写入成功后，再用 os.replace 整体替换正式文件。

        os.replace 在同一磁盘上是原子操作。这样即使保存过程中断电，
        正式文件也只会是“旧版本”或“新版本”，不会变成半个 JSON。
        """
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            json_text = json.dumps(data, ensure_ascii=False, indent=2)
            with tmp_path.open("w", encoding="utf-8", newline="\n") as file:
                file.write(json_text)
                file.flush()
                os.fsync(file.fileno())  # 尽量确保内容真正写入磁盘
            os.replace(tmp_path, self.path)
            self.last_error = ""
            return True
        except OSError as exc:
            self.last_error = str(exc)
            # 清理可能残留的临时文件；清理失败不影响错误结果的返回。
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            return False


# ============================================================
# 五、通用弹窗：添加内容 / 编辑内容 / 删除确认
# ============================================================
class BaseDialog(ctk.CTkToplevel):
    """
    弹窗基类：统一处理居中、置顶、模态和关闭行为。

    子类只需要搭建自己的界面。使用模态（grab_set）后，
    用户必须先处理弹窗，才能继续点击主窗口。
    """

    def __init__(self, parent: "ReviewApp", width: int, height: int, title: str) -> None:
        super().__init__(parent)
        self.parent_app = parent
        self._dialog_width = width
        self._dialog_height = height
        # 记住设计高度，作为 fit_height 的下限：内容不多时保持原来的观感。
        self._base_height = height

        self.title(title)
        self.configure(fg_color=COLORS["bg"])
        self.resizable(False, False)
        self.transient(parent)  # 让弹窗始终跟随主窗口
        center_window(self, width, height)

        # 等窗口真正显示后再抢焦点/设置模态，
        # 否则部分 Windows 环境会报 "window not viewable"。
        self.after(60, self._activate)
        self.bind("<Escape>", lambda _event: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _activate(self) -> None:
        """弹窗显示后的初始化：置顶、抓取输入、设置焦点。"""
        if not self.winfo_exists():
            return
        try:
            self.grab_set()
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def fit_height(self) -> None:
        """
        按内容实际需要的高度调整弹窗。

        节点换行后内容会变高；固定高度会把底部的保存按钮裁掉。
        这里量一次内容高度（Tk 返回的是屏幕像素，需要先除以界面缩放），
        只调整高度，宽度和窗口位置保持不动。
        """
        if not self.winfo_exists():
            return

        self.update_idletasks()
        scaling = ctk.ScalingTracker.get_window_scaling(self) or 1.0
        need = int(self.winfo_reqheight() / scaling + 0.999)
        need = max(need, self._base_height)
        need = min(need, self.winfo_screenheight() - 80)
        if abs(need - self._dialog_height) < 2:
            return

        self._dialog_height = need
        x = self.winfo_x()
        y = min(
            max(0, self.winfo_y()),
            max(0, self.winfo_screenheight() - need - 60),
        )
        self.geometry(f"{self._dialog_width}x{need}+{x}+{y}")

    def close(self) -> None:
        """安全关闭：先释放模态，再销毁窗口。"""
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


class TimelineEditor(ctk.CTkFrame):
    """
    可增删节点的复习时间轴编辑器。

    每个节点占一列：第 N 次 / 天数输入框 / 对应日期；节点超过
    TIMELINE_COLUMNS 个时自动换行。点「增加节点」会按艾宾浩斯曲线
    补下一个值，点「删除节点」则移除最后一个节点。
    """

    def __init__(
        self,
        master: tk.Misc,
        intervals: list[int] | tuple[int, ...],
        *,
        base_day: date | None = None,
        entry_height: int = 38,
        entry_font_size: int = 14,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        # 预览日期的基准：新增内容用今天，修改旧任务用它的添加日期。
        self._base_day = base_day or today_date()
        self._entry_height = entry_height
        self._entry_font_size = entry_font_size
        self._on_change = on_change
        self._preview_job: str | None = None

        self.variables: list[tk.StringVar] = [
            self._make_variable(int(value)) for value in intervals
        ]
        self.cells: list[ctk.CTkFrame] = []
        self.date_labels: list[ctk.CTkLabel] = []
        self.entries: list[ctk.CTkEntry] = []

        self._grid = ctk.CTkFrame(self, fg_color="transparent")
        self._grid.pack(fill="x")
        for column in range(TIMELINE_COLUMNS):
            self._grid.grid_columnconfigure(
                column, weight=1, uniform="timeline_node"
            )

        self._build_toolbar()
        self._render_cells()

    # --------------------------------------------------------
    # 基础构建
    # --------------------------------------------------------
    def _make_variable(self, value: int) -> tk.StringVar:
        """创建一个绑定输入框的变量，并接上日期预览的防抖刷新。"""
        variable = tk.StringVar(value=str(value))
        variable.trace_add("write", lambda *_args: self._schedule_preview())
        return variable

    def _build_toolbar(self) -> None:
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", pady=(8, 0))

        self.add_button = ctk.CTkButton(
            toolbar,
            text="＋ 增加节点",
            width=104,
            height=28,
            corner_radius=8,
            fg_color="transparent",
            hover_color=COLORS["accent_soft"],
            border_width=1,
            border_color=COLORS["border"],
            text_color=COLORS["accent_text"],
            font=ui_font(9, "bold"),
            command=self.add_node,
        )
        self.add_button.pack(side="left")

        self.remove_button = ctk.CTkButton(
            toolbar,
            text="－ 删除节点",
            width=104,
            height=28,
            corner_radius=8,
            fg_color="transparent",
            hover_color=COLORS["red_soft"],
            border_width=1,
            border_color=COLORS["border"],
            text_color=COLORS["muted"],
            font=ui_font(9, "bold"),
            command=self.remove_node,
        )
        self.remove_button.pack(side="left", padx=(8, 0))

        self.count_label = ctk.CTkLabel(
            toolbar, text="", font=ui_font(9), text_color=COLORS["faint"],
        )
        self.count_label.pack(side="right")

    def _render_cells(self) -> None:
        """按当前节点数量重画输入框（超过每行上限时自动换行）。"""
        for cell in self.cells:
            cell.destroy()
        self.cells = []
        self.date_labels = []
        self.entries = []

        for index, variable in enumerate(self.variables):
            row, column = divmod(index, TIMELINE_COLUMNS)

            cell = ctk.CTkFrame(self._grid, fg_color="transparent")
            cell.grid(
                row=row,
                column=column,
                sticky="ew",
                padx=(0 if column == 0 else 5, 0),
                pady=(0 if row == 0 else 8, 0),
            )

            ctk.CTkLabel(
                cell, text=f"第 {index + 1} 次", font=ui_font(9, "bold"),
                text_color=COLORS["faint"],
            ).pack(anchor="w", pady=(0, 3))

            entry = ctk.CTkEntry(
                cell,
                textvariable=variable,
                height=self._entry_height,
                corner_radius=9,
                fg_color=COLORS["card_alt"],
                border_color=COLORS["border"],
                text_color=COLORS["text"],
                font=ui_font(self._entry_font_size, "bold"),
                justify="center",
            )
            entry.pack(fill="x")

            date_label = ctk.CTkLabel(
                cell, text="—", font=ui_font(8),
                text_color=COLORS["faint"],
            )
            date_label.pack(pady=(3, 0))

            self.cells.append(cell)
            self.entries.append(entry)
            self.date_labels.append(date_label)

        self._update_preview()
        self._update_buttons()

    # --------------------------------------------------------
    # 增删节点
    # --------------------------------------------------------
    def add_node(self) -> None:
        """按艾宾浩斯曲线追加一个节点（默认值自动取曲线的下一个点）。"""
        if not self.can_add():
            return

        self.variables.append(
            self._make_variable(next_ebbinghaus_day(self._valid_days()))
        )
        self._render_cells()
        self._notify_change()
        # 新节点直接聚焦并选中，方便马上改成自己想要的天数。
        self.after(10, self._focus_last_entry)

    def remove_node(self) -> None:
        """删除最后一个节点；至少保留 MIN_INTERVAL_NODE_COUNT 个。"""
        if len(self.variables) <= MIN_INTERVAL_NODE_COUNT:
            return

        self.variables.pop()
        self._render_cells()
        self._notify_change()

    def reset_default(self) -> None:
        """恢复成默认的 5 个艾宾浩斯节点：第 1 / 2 / 4 / 7 / 15 天。"""
        self.variables = [
            self._make_variable(value) for value in DEFAULT_REVIEW_INTERVALS
        ]
        self._render_cells()
        self._notify_change()

    def focus_first(self) -> None:
        """把焦点放到第一个节点输入框。"""
        self._focus_entry(0)

    def _focus_last_entry(self) -> None:
        self._focus_entry(-1)

    def _focus_entry(self, index: int) -> None:
        if not self.winfo_exists() or not self.entries:
            return
        try:
            entry = self.entries[index]
            entry.focus_set()
            entry.select_range(0, "end")
        except (tk.TclError, AttributeError, IndexError):
            pass

    # --------------------------------------------------------
    # 状态与校验
    # --------------------------------------------------------
    def can_add(self) -> bool:
        """还能不能再加一个节点。"""
        if len(self.variables) >= MAX_INTERVAL_NODE_COUNT:
            return False
        return max(self._valid_days(), default=0) < MAX_INTERVAL_DAY

    def _valid_days(self) -> list[int]:
        """取出当前输入里合法（正整数）的天数，忽略空值和乱填的内容。"""
        days: list[int] = []
        for variable in self.variables:
            text = variable.get().strip()
            if text.isdecimal():
                value = int(text)
                if 1 <= value <= MAX_INTERVAL_DAY:
                    days.append(value)
        return days

    def read_values(self) -> tuple[list[int] | None, str]:
        """读取全部输入框并校验，返回 (节点列表, 错误提示)。"""
        return validate_review_intervals(
            [variable.get().strip() for variable in self.variables]
        )

    def _update_buttons(self) -> None:
        if not self.winfo_exists():
            return
        self.add_button.configure(
            state="normal" if self.can_add() else "disabled"
        )
        self.remove_button.configure(
            state=(
                "normal"
                if len(self.variables) > MIN_INTERVAL_NODE_COUNT
                else "disabled"
            )
        )
        self.count_label.configure(
            text=(
                f"共 {len(self.variables)} 个节点"
                f"（{MIN_INTERVAL_NODE_COUNT} ~ {MAX_INTERVAL_NODE_COUNT}）"
            )
        )

    def _notify_change(self) -> None:
        if self._on_change is not None:
            self._on_change()

    # --------------------------------------------------------
    # 日期预览
    # --------------------------------------------------------
    def _schedule_preview(self) -> None:
        """输入变化后稍等片刻再刷新日期，避免每敲一个键都重绘。"""
        if self._preview_job is not None:
            try:
                self.after_cancel(self._preview_job)
            except tk.TclError:
                pass
        self._preview_job = self.after(80, self._update_preview)

    def _update_preview(self) -> None:
        """刷新每个节点下方的日期；输入不合法时显示“—”。"""
        self._preview_job = None
        if not self.winfo_exists():
            return

        for variable, label in zip(self.variables, self.date_labels):
            text = variable.get().strip()
            if text.isdecimal() and 1 <= int(text) <= MAX_INTERVAL_DAY:
                target = self._base_day + timedelta(days=int(text) - 1)
                label.configure(text=format_month_day(target))
            else:
                label.configure(text="—")

        self._update_buttons()

    def destroy(self) -> None:
        """销毁前取消尚未执行的预览任务。"""
        if self._preview_job is not None:
            try:
                self.after_cancel(self._preview_job)
            except tk.TclError:
                pass
            self._preview_job = None
        super().destroy()


class AddItemDialog(BaseDialog):
    """新增背诵内容的弹窗（每条内容单独设置复习时间轴）。"""

    def __init__(
        self,
        parent: "ReviewApp",
        on_submit: Callable[[str, str, list[int]], bool],
    ) -> None:
        super().__init__(parent, width=560, height=660, title="添加背诵内容")
        self.on_submit = on_submit
        self._build_ui()

    def _build_ui(self) -> None:
        # ---------- 顶部标题区 ----------
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(24, 18))

        logo = ctk.CTkFrame(header, width=46, height=46, corner_radius=14,
                            fg_color=COLORS["accent"])
        logo.pack(side="left")
        logo.pack_propagate(False)
        ctk.CTkLabel(
            logo, text="＋", font=ui_font(22, "bold"),
            text_color=COLORS["white"],
        ).place(relx=0.5, rely=0.5, anchor="center")

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(
            title_box, text="添加背诵内容", font=ui_font(19, "bold"),
            text_color=COLORS["text"], anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_box,
            text="这条内容的复习时间轴可以单独设置",
            font=ui_font(11),
            text_color=COLORS["muted"], anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # 系统标题栏已经有关闭按钮；按 Esc 也能关闭，不再重复放一个。
        # ---------- 表单卡片 ----------
        card = ctk.CTkFrame(
            self, fg_color=COLORS["card"], corner_radius=18,
            border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="both", expand=True, padx=24, pady=(0, 24))

        form = ctk.CTkFrame(card, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=22, pady=20)

        # 标题输入
        ctk.CTkLabel(
            form, text="背诵内容标题 *", font=ui_font(12, "bold"),
            text_color=COLORS["text"], anchor="w",
        ).pack(anchor="w")
        self.title_entry = ctk.CTkEntry(
            form, height=42, corner_radius=11,
            fg_color=COLORS["card_alt"], border_color=COLORS["border"],
            text_color=COLORS["text"], placeholder_text_color=COLORS["faint"],
            placeholder_text="例如：滕王阁序 / 英语 Unit 5 单词",
            font=ui_font(13),
        )
        self.title_entry.pack(fill="x", pady=(7, 15))
        self.title_entry.bind("<Return>", lambda _event: self._submit())

        # 备注输入
        ctk.CTkLabel(
            form, text="备注（可选）", font=ui_font(12, "bold"),
            text_color=COLORS["text"], anchor="w",
        ).pack(anchor="w")
        self.note_text = ctk.CTkTextbox(
            form, height=88, corner_radius=11,
            fg_color=COLORS["card_alt"], border_width=1,
            border_color=COLORS["border"], text_color=COLORS["text"],
            font=ui_font(12), wrap="word",
        )
        self.note_text.pack(fill="x", pady=(7, 13))

        # ---------- 本次内容专属的复习时间轴 ----------
        timeline_head = ctk.CTkFrame(form, fg_color="transparent")
        timeline_head.pack(fill="x")
        ctk.CTkLabel(
            timeline_head,
            text="本次复习时间轴（距添加日的第几天）",
            font=ui_font(12, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        ).pack(side="left")

        ctk.CTkButton(
            timeline_head,
            text="恢复默认",
            width=74,
            height=26,
            corner_radius=8,
            fg_color=COLORS["card_alt"],
            hover_color=COLORS["border"],
            text_color=COLORS["muted"],
            font=ui_font(9, "bold"),
            command=self._reset_timeline,
        ).pack(side="right")

        self.timeline = TimelineEditor(
            form,
            DEFAULT_REVIEW_INTERVALS,
            entry_height=38,
            entry_font_size=14,
            on_change=self.fit_height,
        )
        self.timeline.pack(fill="x", pady=(8, 0))

        ctk.CTkLabel(
            form,
            text="第 1 天即添加当天；第 2 天为次日。可增减节点，只作用于本条内容。",
            font=ui_font(9),
            text_color=COLORS["faint"],
            anchor="w",
        ).pack(anchor="w", pady=(7, 0))

        # 错误提示行：高度固定，避免出现错误时界面上下跳动。
        self.error_label = ctk.CTkLabel(
            form, text="", font=ui_font(11, "bold"),
            text_color=COLORS["red"], anchor="w", height=22,
        )
        self.error_label.pack(fill="x", pady=(6, 0))

        # ---------- 底部按钮 ----------
        actions = ctk.CTkFrame(form, fg_color="transparent")
        actions.pack(fill="x", pady=(8, 0))

        ctk.CTkButton(
            actions, text="取消", width=92, height=40, corner_radius=11,
            fg_color=COLORS["card_alt"], hover_color=COLORS["border"],
            text_color=COLORS["muted"], font=ui_font(12, "bold"),
            command=self.close,
        ).pack(side="right", padx=(10, 0))

        ctk.CTkButton(
            actions, text="添加并生成计划", width=150, height=40, corner_radius=11,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["white"], font=ui_font(12, "bold"),
            command=self._submit,
        ).pack(side="right")

        # 打开弹窗后直接聚焦标题输入框，用户可以直接打字。
        self.after(180, self.title_entry.focus_set)
        # 编辑器比原来的 5 个输入框多了一行按钮，内容比设计高度略高，先校准一次。
        self.fit_height()

    def _read_timeline(self) -> tuple[list[int] | None, str]:
        """读取本条内容的时间轴输入框并校验。"""
        return self.timeline.read_values()

    def _reset_timeline(self) -> None:
        """把本条内容的时间轴恢复为默认的 1/2/4/7/15。"""
        self.timeline.reset_default()
        self.error_label.configure(text="")

    def _submit(self) -> None:
        """校验标题、备注和本条时间轴，然后交给主窗口保存。"""
        title = self.title_entry.get().strip()
        note = self.note_text.get("1.0", "end-1c").strip()

        if not title:
            self.error_label.configure(text="请先填写背诵内容标题")
            self.title_entry.focus_set()
            return
        if len(title) > 60:
            self.error_label.configure(text="标题过长，请控制在 60 个字符以内")
            self.title_entry.focus_set()
            return
        if len(note) > 1000:
            self.error_label.configure(text="备注过长，请控制在 1000 个字符以内")
            return

        intervals, error = self._read_timeline()
        if intervals is None:
            self.error_label.configure(text=error)
            return

        # on_submit 返回 False 通常意味着保存文件失败，
        # 此时不关闭弹窗，让用户重试或检查目录权限。
        if self.on_submit(title, note, intervals):
            self.close()


class ConfirmDialog(BaseDialog):
    """删除确认弹窗，避免误删数据。"""

    def __init__(
        self,
        parent: "ReviewApp",
        title: str,
        message: str,
        on_confirm: Callable[[], None],
    ) -> None:
        super().__init__(parent, width=440, height=264, title=title)
        self.on_confirm = on_confirm
        self._build_ui(title, message)

    def _build_ui(self, title: str, message: str) -> None:
        card = ctk.CTkFrame(
            self, fg_color=COLORS["card"], corner_radius=18,
            border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="both", expand=True, padx=14, pady=14)

        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=22, pady=20)

        top = ctk.CTkFrame(content, fg_color="transparent")
        top.pack(fill="x")

        icon = ctk.CTkFrame(top, width=42, height=42, corner_radius=13,
                            fg_color=COLORS["red_soft"])
        icon.pack(side="left")
        icon.pack_propagate(False)
        ctk.CTkLabel(
            icon, text="!", font=ui_font(20, "bold"),
            text_color=COLORS["red"],
        ).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            top, text=title, font=ui_font(17, "bold"),
            text_color=COLORS["text"], anchor="w",
        ).pack(side="left", padx=(11, 0))

        ctk.CTkLabel(
            content, text=message, font=ui_font(12),
            text_color=COLORS["muted"], anchor="w", justify="left",
            wraplength=340,
        ).pack(fill="x", pady=(18, 0))

        actions = ctk.CTkFrame(content, fg_color="transparent")
        actions.pack(fill="x", side="bottom", pady=(18, 0))

        ctk.CTkButton(
            actions, text="取消", width=92, height=38, corner_radius=11,
            fg_color=COLORS["card_alt"], hover_color=COLORS["border"],
            text_color=COLORS["muted"], font=ui_font(12, "bold"),
            command=self.close,
        ).pack(side="right", padx=(10, 0))

        ctk.CTkButton(
            actions, text="确认删除", width=106, height=38, corner_radius=11,
            fg_color=COLORS["red"], hover_color=COLORS["red_hover"],
            text_color=COLORS["white"], font=ui_font(12, "bold"),
            command=self._confirm,
        ).pack(side="right")

    def _confirm(self) -> None:
        """先执行外部传入的删除逻辑，再关闭弹窗。"""
        self.on_confirm()
        self.close()


class ItemEditDialog(BaseDialog):
    """
    “编辑已保存的背诵内容”弹窗。

    只修改标题和备注；创建日期、复习时间轴和每个节点的完成状态都保持原样，
    因此补一句备注或改个错别字，不会把复习计划打乱。
    """

    def __init__(
        self,
        parent: "ReviewApp",
        item_id: str,
        initial_title: str,
        initial_note: str,
        intervals: list[int],
        on_save: Callable[[str, str], bool],
    ) -> None:
        super().__init__(parent, width=560, height=560, title="编辑背诵内容")
        # 记录所属任务的 id：同一个弹窗只服务一条内容，
        # 换一条再打开时主窗口会重建弹窗，避免改到别的任务上。
        self.item_id = item_id
        self.on_save = on_save
        self._initial_title = initial_title
        self._initial_note = initial_note
        self._intervals = list(intervals)
        self._build_ui()

    def _build_ui(self) -> None:
        # ---------- 顶部标题区 ----------
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(24, 18))

        logo = ctk.CTkFrame(header, width=46, height=46, corner_radius=14,
                            fg_color=COLORS["accent"])
        logo.pack(side="left")
        logo.pack_propagate(False)
        ctk.CTkLabel(
            logo, text="✎", font=ui_font(20, "bold"),
            text_color=COLORS["white"],
        ).place(relx=0.5, rely=0.5, anchor="center")

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(
            title_box, text="编辑背诵内容", font=ui_font(19, "bold"),
            text_color=COLORS["text"], anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_box,
            text="只改标题和备注，复习进度与时间轴保持不变",
            font=ui_font(11),
            text_color=COLORS["muted"], anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # ---------- 表单卡片 ----------
        card = ctk.CTkFrame(
            self, fg_color=COLORS["card"], corner_radius=18,
            border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="both", expand=True, padx=24, pady=(0, 24))

        form = ctk.CTkFrame(card, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=22, pady=20)

        # 标题输入：预填原来的标题，打开后整段选中，方便直接替换。
        ctk.CTkLabel(
            form, text="背诵内容标题 *", font=ui_font(12, "bold"),
            text_color=COLORS["text"], anchor="w",
        ).pack(anchor="w")
        self.title_entry = ctk.CTkEntry(
            form, height=42, corner_radius=11,
            fg_color=COLORS["card_alt"], border_color=COLORS["border"],
            text_color=COLORS["text"], placeholder_text_color=COLORS["faint"],
            placeholder_text="例如：滕王阁序 / 英语 Unit 5 单词",
            font=ui_font(13),
        )
        self.title_entry.pack(fill="x", pady=(7, 15))
        self.title_entry.insert(0, self._initial_title)
        self.title_entry.bind("<Return>", lambda _event: self._submit())

        # 备注输入：多行内容原样回填，换行不会丢。
        ctk.CTkLabel(
            form, text="备注（可选）", font=ui_font(12, "bold"),
            text_color=COLORS["text"], anchor="w",
        ).pack(anchor="w")
        self.note_text = ctk.CTkTextbox(
            form, height=150, corner_radius=11,
            fg_color=COLORS["card_alt"], border_width=1,
            border_color=COLORS["border"], text_color=COLORS["text"],
            font=ui_font(12), wrap="word",
        )
        self.note_text.pack(fill="both", expand=True, pady=(7, 10))
        if self._initial_note:
            self.note_text.insert("1.0", self._initial_note)

        # 说明文字：时间轴不在这里改，避免用户误以为改备注会让复习重新计时。
        ctk.CTkLabel(
            form,
            text=(
                f"当前复习时间轴：第 {format_interval_summary(self._intervals)} 天。"
                "需要调整节点，请回到「全部计划」点「时间轴」。"
            ),
            font=ui_font(9),
            text_color=COLORS["faint"],
            anchor="w",
            justify="left",
            wraplength=460,
        ).pack(anchor="w")

        # 错误提示行：高度固定，避免出现错误时界面上下跳动。
        self.error_label = ctk.CTkLabel(
            form, text="", font=ui_font(11, "bold"),
            text_color=COLORS["red"], anchor="w", height=22,
        )
        self.error_label.pack(fill="x", pady=(6, 0))

        # ---------- 底部按钮 ----------
        actions = ctk.CTkFrame(form, fg_color="transparent")
        actions.pack(fill="x", pady=(8, 0))

        ctk.CTkButton(
            actions, text="取消", width=92, height=40, corner_radius=11,
            fg_color=COLORS["card_alt"], hover_color=COLORS["border"],
            text_color=COLORS["muted"], font=ui_font(12, "bold"),
            command=self.close,
        ).pack(side="right", padx=(10, 0))

        ctk.CTkButton(
            actions, text="保存修改", width=122, height=40, corner_radius=11,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["white"], font=ui_font(12, "bold"),
            command=self._submit,
        ).pack(side="right")

        self.after(180, self._focus_title)

    def _focus_title(self) -> None:
        """聚焦标题输入框，并选中原文，方便随手整句替换。"""
        if not self.winfo_exists():
            return
        try:
            self.title_entry.focus_set()
            self.title_entry.select_range(0, "end")
        except (tk.TclError, AttributeError):
            # 个别平台/版本的输入框没有 select_range，退化为只聚焦。
            pass

    def _submit(self) -> None:
        """校验标题和备注，然后交给主窗口保存。"""
        title = self.title_entry.get().strip()
        note = self.note_text.get("1.0", "end-1c").strip()

        if not title:
            self.error_label.configure(text="请先填写背诵内容标题")
            self.title_entry.focus_set()
            return
        if len(title) > 60:
            self.error_label.configure(text="标题过长，请控制在 60 个字符以内")
            self.title_entry.focus_set()
            return
        if len(note) > 1000:
            self.error_label.configure(text="备注过长，请控制在 1000 个字符以内")
            return

        # 保存失败时（例如目录不可写）保持弹窗打开，并把原因写在错误行上。
        if self.on_save(title, note):
            self.close()
        else:
            self.error_label.configure(text="保存失败，请检查程序目录是否可写")


class ItemTimelineDialog(BaseDialog):
    """
    “调整这一条背诵的时间轴”弹窗。

    设计要点：
    - 每个任务单独设置复习节点，默认 5 个，可增删（1 ~ 10 个）；
    - 增加节点时默认取艾宾浩斯曲线的下一个点；
    - 这里的数字表示“添加后的第几天”，不是相邻两次的间隔；
    - 修改已有任务时，按它最初的添加日期重新计算日期；
      已完成且仍然保留的节点会继续保留。
    """

    def __init__(
        self,
        parent: "ReviewApp",
        item_title: str,
        base_day: date,
        intervals: list[int],
        on_save: Callable[[list[int]], bool],
    ) -> None:
        super().__init__(
            parent,
            width=600,
            height=600,
            title="调整复习时间轴",
        )
        self.item_title = item_title
        self.base_day = base_day
        self.on_save = on_save
        self._build_ui(intervals)

    def _build_ui(self, intervals: list[int]) -> None:
        # ---------- 顶部标题 ----------
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(24, 18))

        logo = ctk.CTkFrame(
            header, width=46, height=46, corner_radius=14,
            fg_color=COLORS["accent"],
        )
        logo.pack(side="left")
        logo.pack_propagate(False)
        ctk.CTkLabel(
            logo, text="↻", font=ui_font(23, "bold"),
            text_color=COLORS["white"],
        ).place(relx=0.5, rely=0.5, anchor="center")

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(
            title_box, text="调整复习时间轴", font=ui_font(19, "bold"),
            text_color=COLORS["text"], anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_box, text="只修改这一条背诵内容", font=ui_font(11),
            text_color=COLORS["muted"], anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # ---------- 表单卡片 ----------
        card = ctk.CTkFrame(
            self, fg_color=COLORS["card"], corner_radius=18,
            border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="both", expand=True, padx=24, pady=(0, 24))

        form = ctk.CTkFrame(card, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=22, pady=20)

        # 说明：只作用于当前任务，以及重新计算日期的规则。
        notice = ctk.CTkFrame(
            form, fg_color=COLORS["accent_soft"], corner_radius=11,
        )
        notice.pack(fill="x", pady=(0, 15))
        ctk.CTkLabel(
            notice,
            text=(
                f"正在调整「{self.item_title}」。\n"
                "修改后会从添加当天重新计算日期；已完成的节点如果仍在时间轴"
                "中会保留，被移除的节点会丢失完成记录。"
            ),
            font=ui_font(10),
            text_color=COLORS["accent_text"],
            wraplength=480,
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=13, pady=10)

        # ---------- 节点输入区 ----------
        section_head = ctk.CTkFrame(form, fg_color="transparent")
        section_head.pack(fill="x")
        ctk.CTkLabel(
            section_head,
            text="复习节点（距添加日的第几天）",
            font=ui_font(12, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        ).pack(side="left")

        ctk.CTkButton(
            section_head,
            text="恢复默认",
            width=78,
            height=27,
            corner_radius=8,
            fg_color=COLORS["card_alt"],
            hover_color=COLORS["border"],
            text_color=COLORS["muted"],
            font=ui_font(9, "bold"),
            command=self._reset_to_default,
        ).pack(side="right")

        self.timeline = TimelineEditor(
            form,
            list(intervals) or list(DEFAULT_REVIEW_INTERVALS),
            base_day=self.base_day,
            entry_height=42,
            entry_font_size=15,
            on_change=self.fit_height,
        )
        self.timeline.pack(fill="x", pady=(9, 0))

        ctk.CTkLabel(
            form,
            text="例：1 = 添加当天，2 = 次日。可增减节点，节点必须递增。",
            font=ui_font(9),
            text_color=COLORS["faint"],
            anchor="w",
        ).pack(anchor="w", pady=(6, 0))

        # ---------- 错误提示 ----------
        self.error_label = ctk.CTkLabel(
            form, text="", font=ui_font(10, "bold"),
            text_color=COLORS["red"], anchor="w", height=22,
        )
        self.error_label.pack(fill="x", pady=(6, 0))

        # ---------- 底部按钮 ----------
        actions = ctk.CTkFrame(form, fg_color="transparent")
        actions.pack(fill="x", pady=(6, 0))

        ctk.CTkButton(
            actions, text="取消", width=92, height=40, corner_radius=11,
            fg_color=COLORS["card_alt"], hover_color=COLORS["border"],
            text_color=COLORS["muted"], font=ui_font(12, "bold"),
            command=self.close,
        ).pack(side="right", padx=(10, 0))

        ctk.CTkButton(
            actions, text="保存时间轴", width=122, height=40, corner_radius=11,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["white"], font=ui_font(12, "bold"),
            command=self._submit,
        ).pack(side="right")

        # 打开后直接聚焦第一个节点，方便连续输入。
        self.after(180, self.timeline.focus_first)
        # 已有任务可能不是 5 个节点；先按实际内容把窗口撑到需要的高度。
        self.fit_height()

    def _read_inputs(self) -> tuple[list[int] | None, str]:
        """读取时间轴输入框并校验，返回 (节点列表, 错误提示)。"""
        return self.timeline.read_values()

    def _reset_to_default(self) -> None:
        """一键恢复标准艾宾浩斯时间轴。"""
        self.timeline.reset_default()
        self.error_label.configure(text="")

    def _submit(self) -> None:
        """校验通过后调用主窗口保存设置。"""
        intervals, error = self._read_inputs()
        if intervals is None:
            self.error_label.configure(text=error)
            return

        # 主窗口保存成功返回 True；失败时弹窗保持打开，方便用户重试。
        if self.on_save(intervals):
            self.close()
        else:
            self.error_label.configure(text="保存失败，请检查程序目录是否可写")


# ============================================================
# 六、主窗口
# ============================================================
class ReviewApp(ctk.CTk):
    """应用主窗口。界面由左侧边栏 + 右侧内容区组成。"""

    def __init__(self) -> None:
        # 先建立 Tk 根窗口，才能加载字体和创建控件。
        super().__init__()

        # ---------- 加载数据 ----------
        self.store = DataStore(DATA_FILE)
        self.data = self.store.load()

        # 根据保存的设置决定初始外观，默认跟随系统。
        saved_mode = self.data.get("settings", {}).get("appearance", "system")
        if saved_mode not in APPEARANCE_MODES.values():
            saved_mode = "system"
        self.appearance_mode = saved_mode
        ctk.set_appearance_mode(saved_mode)

        # ---------- 运行时状态 ----------
        self.current_view = "today"       # today / all
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        self._refresh_job: str | None = None
        self._toast_job: str | None = None
        self._add_dialog: AddItemDialog | None = None
        self._delete_dialog: ConfirmDialog | None = None
        self._timeline_dialog: ItemTimelineDialog | None = None
        self._edit_dialog: ItemEditDialog | None = None

        # ---------- 窗口基础设置 ----------
        self.title(APP_NAME)
        self.configure(fg_color=COLORS["bg"])
        self.minsize(980, 650)

        # 根据屏幕大小计算窗口尺寸：优先 1180x780，
        # 小屏幕上自动缩小，避免窗口超出可用区域。
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = min(1180, max(980, screen_w - 160))
        height = min(780, max(650, screen_h - 130))
        center_window(self, width, height)

        self._set_icon()

        # 主窗口分两列：左侧导航固定宽度，右侧内容自适应。
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=0, minsize=248)
        self.grid_columnconfigure(1, weight=1)

        # ---------- 搭建界面 ----------
        self._build_sidebar()
        self._build_main_area()
        self._bind_shortcuts()
        self.show_view("today")
        self._update_sidebar_stats()

        # 数据文件损坏时，启动后给用户一个明确提示。
        if self.store.load_warning:
            self.after(650, lambda: self.show_toast(self.store.load_warning, "warning"))

        # 用户点右上角关闭时，走统一的关闭流程。
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # --------------------------------------------------------
    # 6.1 窗口图标和快捷键
    # --------------------------------------------------------
    def _set_icon(self) -> None:
        """如果同目录下有图标文件，就应用到窗口和任务栏。"""
        if not ICON_FILE.exists():
            return
        try:
            self.iconbitmap(str(ICON_FILE))
        except tk.TclError:
            # 图标损坏或平台不支持时忽略，不影响程序运行。
            pass

    def _bind_shortcuts(self) -> None:
        """绑定常用快捷键。"""
        self.bind("<Control-n>", lambda _event: self.open_add_dialog())
        self.bind("<Control-N>", lambda _event: self.open_add_dialog())
        # F5 用于手动刷新“今天”的判断，方便程序跨天一直开着时使用。
        self.bind("<F5>", lambda _event: self._refresh_today_at_midnight())

    # --------------------------------------------------------
    # 6.2 左侧边栏
    # --------------------------------------------------------
    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(
            self, fg_color=COLORS["sidebar"], corner_radius=0, width=248,
        )
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)  # 固定侧边栏宽度
        sidebar.grid_columnconfigure(0, weight=1)
        # 第 4 行是弹性空白，把外观设置和保存状态推到底部。
        sidebar.grid_rowconfigure(4, weight=1)

        # ---------- 品牌区 ----------
        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=20, pady=(26, 20))

        logo = ctk.CTkFrame(brand, width=44, height=44, corner_radius=14,
                            fg_color=COLORS["accent"])
        logo.pack(side="left")
        logo.pack_propagate(False)
        ctk.CTkLabel(
            logo, text="忆", font=ui_font(20, "bold"),
            text_color=COLORS["white"],
        ).place(relx=0.5, rely=0.5, anchor="center")

        brand_text = ctk.CTkFrame(brand, fg_color="transparent")
        brand_text.pack(side="left", padx=(11, 0))
        ctk.CTkLabel(
            brand_text, text="拾忆", font=ui_font(18, "bold"),
            text_color=COLORS["text"], anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand_text, text="艾宾浩斯背诵助手", font=ui_font(10),
            text_color=COLORS["muted"], anchor="w",
        ).pack(anchor="w", pady=(1, 0))

        # ---------- 导航区 ----------
        ctk.CTkLabel(
            sidebar, text="工作台", font=ui_font(10, "bold"),
            text_color=COLORS["faint"], anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=26, pady=(6, 6))

        nav_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav_frame.grid(row=2, column=0, sticky="ew", padx=14)

        nav_items = (
            ("today", "◷   今日复习"),
            ("all", "▤   全部计划"),
        )
        for key, text in nav_items:
            button = ctk.CTkButton(
                nav_frame,
                text=text,
                height=44,
                corner_radius=12,
                anchor="w",
                font=ui_font(13, "bold"),
                fg_color="transparent",
                hover_color=COLORS["accent_soft"],
                text_color=COLORS["muted"],
                command=lambda view=key: self.show_view(view),
            )
            button.pack(fill="x", pady=3)
            self.nav_buttons[key] = button

        # ---------- 今日进度卡 ----------
        stat_card = ctk.CTkFrame(
            sidebar, fg_color=COLORS["card"], corner_radius=16,
            border_width=1, border_color=COLORS["border"],
        )
        stat_card.grid(row=3, column=0, sticky="ew", padx=16, pady=(18, 0))

        stat_inner = ctk.CTkFrame(stat_card, fg_color="transparent")
        stat_inner.pack(fill="x", padx=16, pady=14)

        stat_head = ctk.CTkFrame(stat_inner, fg_color="transparent")
        stat_head.pack(fill="x")
        ctk.CTkLabel(
            stat_head, text="今日进度", font=ui_font(11, "bold"),
            text_color=COLORS["text"], anchor="w",
        ).pack(side="left")
        self.stats_percent = ctk.CTkLabel(
            stat_head, text="0%", font=ui_font(11, "bold"),
            text_color=COLORS["accent_text"], anchor="e",
        )
        self.stats_percent.pack(side="right")

        self.stats_ratio = ctk.CTkLabel(
            stat_inner, text="0 / 0", font=ui_font(25, "bold"),
            text_color=COLORS["text"], anchor="w",
        )
        self.stats_ratio.pack(anchor="w", pady=(4, 6))

        self.stats_bar = ctk.CTkProgressBar(
            stat_inner, height=7, corner_radius=4,
            fg_color=COLORS["track"], progress_color=COLORS["accent"],
        )
        self.stats_bar.pack(fill="x")
        self.stats_bar.set(0)

        self.stats_detail = ctk.CTkLabel(
            stat_inner, text="今天暂无复习安排", font=ui_font(10),
            text_color=COLORS["muted"], anchor="w",
        )
        self.stats_detail.pack(anchor="w", pady=(8, 0))

        # ---------- 外观设置 ----------
        appearance_box = ctk.CTkFrame(sidebar, fg_color="transparent")
        appearance_box.grid(row=5, column=0, sticky="ew", padx=18, pady=(18, 0))

        ctk.CTkLabel(
            appearance_box, text="◐   外观", font=ui_font(10, "bold"),
            text_color=COLORS["faint"], anchor="w",
        ).pack(anchor="w", pady=(0, 6))

        self.appearance_choice = tk.StringVar(
            value=APPEARANCE_LABELS[self.appearance_mode]
        )
        appearance_menu = ctk.CTkOptionMenu(
            appearance_box,
            values=list(APPEARANCE_LABELS.values()),
            variable=self.appearance_choice,
            command=self._change_appearance,
            height=34,
            corner_radius=10,
            fg_color=COLORS["card"],
            button_color=COLORS["accent_soft"],
            button_hover_color=COLORS["track"],
            text_color=COLORS["text"],
            dropdown_fg_color=COLORS["card"],
            dropdown_hover_color=COLORS["accent_soft"],
            dropdown_text_color=COLORS["text"],
            font=ui_font(11, "bold"),
            dropdown_font=ui_font(11),
            anchor="w",
        )
        appearance_menu.pack(fill="x")

        # ---------- 保存状态 ----------
        footer = ctk.CTkFrame(sidebar, fg_color="transparent")
        footer.grid(row=6, column=0, sticky="ew", padx=20, pady=(14, 20))

        self.save_label = ctk.CTkLabel(
            footer, text="●  数据已就绪", font=ui_font(10),
            text_color=COLORS["green"], anchor="w",
        )
        self.save_label.pack(anchor="w")
        ctk.CTkLabel(
            footer, text="本地 JSON · 与程序同目录", font=ui_font(9),
            text_color=COLORS["faint"], anchor="w",
        ).pack(anchor="w", pady=(3, 0))

    # --------------------------------------------------------
    # 6.3 右侧主区域
    # --------------------------------------------------------
    def _build_main_area(self) -> None:
        main = ctk.CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        # ---------- 固定页头 ----------
        header = ctk.CTkFrame(main, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=34, pady=(28, 18))
        header.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")

        self.header_title = ctk.CTkLabel(
            title_box, text="今日复习", font=ui_font(28, "bold"),
            text_color=COLORS["text"], anchor="w",
        )
        self.header_title.pack(anchor="w")

        self.header_subtitle = ctk.CTkLabel(
            title_box, text="", font=ui_font(12),
            text_color=COLORS["muted"], anchor="w",
        )
        self.header_subtitle.pack(anchor="w", pady=(5, 0))

        # 时间轴现在属于每条背诵内容，添加时在弹窗里单独设置。
        add_btn = ctk.CTkButton(
            header,
            text="＋  添加背诵",
            width=138,
            height=42,
            corner_radius=12,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["white"],
            font=ui_font(13, "bold"),
            command=self.open_add_dialog,
        )
        add_btn.grid(row=0, column=1, sticky="e")

        # ---------- 可滚动内容区 ----------
        body = ctk.CTkFrame(main, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=(34, 22), pady=(0, 24))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)

        self.page = ctk.CTkScrollableFrame(
            body,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["faint"],
        )
        self.page.grid(row=0, column=0, sticky="nsew")

    # --------------------------------------------------------
    # 6.4 页面切换
    # --------------------------------------------------------
    def show_view(self, view: str) -> None:
        """切换“今日复习 / 全部计划”两个页面。"""
        if view not in ("today", "all"):
            return

        self.current_view = view
        self._sync_nav_state()

        today = today_date()
        if view == "today":
            self.header_title.configure(text="今日复习")
            self.header_subtitle.configure(
                text=(
                    f"{format_cn_date(today)}  {WEEKDAYS_CN[today.weekday()]}"
                    "  ·  在遗忘发生前，再记一次。"
                )
            )
            self._render_today()
            self._update_sidebar_stats()
        else:
            self.header_title.configure(text="全部计划")
            self.header_subtitle.configure(
                text="所有背诵内容与完整的复习时间轴，按添加时间排列。"
            )
            self._render_all()
            self._update_sidebar_stats()

        # 切换页面后回到顶部，符合常见阅读习惯。
        try:
            self.page._parent_canvas.yview_moveto(0)  # noqa: SLF001
        except (AttributeError, tk.TclError):
            pass

    def _sync_nav_state(self) -> None:
        """根据当前页面，给导航按钮加上选中样式。"""
        for key, button in self.nav_buttons.items():
            is_active = key == self.current_view
            button.configure(
                fg_color=COLORS["accent_soft"] if is_active else "transparent",
                text_color=COLORS["accent_text"] if is_active else COLORS["muted"],
                hover_color=COLORS["accent_soft"],
            )

    def _clear_page(self) -> None:
        """清空可滚动区域里的旧控件，准备重新绘制当前页面。"""
        for child in self.page.winfo_children():
            child.destroy()

    # --------------------------------------------------------
    # 6.5 今日复习页
    # --------------------------------------------------------
    def _render_today(self) -> None:
        """绘制今日复习页面。"""
        self._clear_page()

        pending = self._pending_tasks()
        completed_today = self._completed_today_count()
        total_today = len(pending) + completed_today

        # ---------- 顶部概览卡 ----------
        hero = ctk.CTkFrame(
            self.page,
            fg_color=COLORS["accent_soft"],
            corner_radius=18,
            border_width=1,
            border_color=COLORS["track"],
        )
        hero.pack(fill="x", pady=(0, 18))
        hero.grid_columnconfigure(0, weight=1)
        hero.grid_columnconfigure(1, weight=0)

        hero_left = ctk.CTkFrame(hero, fg_color="transparent")
        hero_left.grid(row=0, column=0, sticky="nsew", padx=(24, 16), pady=22)

        today = today_date()
        self.hero_eyebrow = ctk.CTkLabel(
            hero_left,
            text=f"TODAY · {today.month}月{today.day}日",
            font=ui_font(9, "bold"),
            text_color=COLORS["accent_text"],
            anchor="w",
        )
        self.hero_eyebrow.pack(anchor="w")

        if len(pending) > 0:
            hero_title_text = f"今天还有 {len(pending)} 项复习"
            hero_subtitle_text = "不用贪多，按计划完成几项，记忆就会更牢。"
        elif total_today > 0:
            hero_title_text = "今天的复习已完成"
            hero_subtitle_text = "每一次按时回顾，都在给长期记忆加固。"
        else:
            hero_title_text = "今天还没有复习安排"
            hero_subtitle_text = "添加一项背诵内容，让遗忘曲线替你安排时间。"

        self.hero_title = ctk.CTkLabel(
            hero_left,
            text=hero_title_text,
            font=ui_font(21, "bold"),
            text_color=COLORS["text"],
            anchor="w",
            justify="left",
        )
        self.hero_title.pack(anchor="w", pady=(5, 0))
        self.hero_subtitle = ctk.CTkLabel(
            hero_left,
            text=hero_subtitle_text,
            font=ui_font(11),
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
        )
        self.hero_subtitle.pack(anchor="w", pady=(6, 0))
        bind_wraplength(hero_left, [self.hero_title, self.hero_subtitle], 10, 240)

        # 右侧进度
        hero_right = ctk.CTkFrame(hero, fg_color="transparent", width=250)
        hero_right.grid(row=0, column=1, sticky="e", padx=(10, 24), pady=22)
        hero_right.grid_propagate(False)

        percent = int(round(completed_today / total_today * 100)) if total_today else 0
        ctk.CTkLabel(
            hero_right, text="今日进度", font=ui_font(10, "bold"),
            text_color=COLORS["muted"], anchor="w",
        ).pack(anchor="w")

        percent_row = ctk.CTkFrame(hero_right, fg_color="transparent")
        percent_row.pack(fill="x", pady=(3, 8))
        ctk.CTkLabel(
            percent_row, text=f"{percent}%", font=ui_font(25, "bold"),
            text_color=COLORS["accent_text"], anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            percent_row, text=f"{completed_today} / {total_today} 项",
            font=ui_font(11), text_color=COLORS["muted"], anchor="e",
        ).pack(side="right", pady=(8, 0))

        hero_bar = ctk.CTkProgressBar(
            hero_right, height=8, corner_radius=4,
            fg_color=COLORS["track"], progress_color=COLORS["accent"],
        )
        hero_bar.pack(fill="x")
        hero_bar.set(completed_today / total_today if total_today else 0)

        # ---------- 列表标题 ----------
        section = ctk.CTkFrame(self.page, fg_color="transparent")
        section.pack(fill="x", pady=(4, 10))
        ctk.CTkLabel(
            section, text="待复习内容", font=ui_font(16, "bold"),
            text_color=COLORS["text"], anchor="w",
        ).pack(side="left")
        if pending:
            ctk.CTkLabel(
                section, text=str(len(pending)), font=ui_font(10, "bold"),
                text_color=COLORS["accent_text"],
                fg_color=COLORS["accent_soft"], corner_radius=8,
                width=26, height=22,
            ).pack(side="left", padx=(8, 0))
            ctk.CTkLabel(
                section, text="按到期先后排序", font=ui_font(10),
                text_color=COLORS["faint"], anchor="e",
            ).pack(side="right")

        # ---------- 待复习卡片 ----------
        if pending:
            for item, review, due in pending:
                self._create_task_card(item, review, due)
        else:
            self._create_empty_today(has_completed=total_today > 0)

        # 底部留白，避免最后一张卡片贴住窗口边缘。
        ctk.CTkFrame(self.page, fg_color="transparent", height=8).pack(fill="x")

    def _create_task_card(
        self, item: dict[str, Any], review: dict[str, Any], due: date
    ) -> None:
        """创建一张“今日待复习”卡片。"""
        card = ctk.CTkFrame(
            self.page,
            fg_color=COLORS["card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 10))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=20, pady=17)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0)

        # 标题
        title_label = ctk.CTkLabel(
            body,
            text=item["title"],
            font=ui_font(16, "bold"),
            text_color=COLORS["text"],
            anchor="w",
            justify="left",
            wraplength=600,
        )
        title_label.grid(row=0, column=0, sticky="ew")

        # 第二行：复习节点 / 到期状态 / 创建日期
        meta = ctk.CTkFrame(body, fg_color="transparent")
        meta.grid(row=1, column=0, sticky="w", pady=(8, 0))

        stage_badge = make_badge(
            meta,
            f"第 {review['day']} 天",
            COLORS["accent_soft"],
            COLORS["accent_text"],
        )
        stage_badge.pack(side="left")

        now = today_date()
        delay = (due - now).days
        if delay < 0:
            due_text = f"已逾期 {abs(delay)} 天"
            due_fg = COLORS["orange_soft"]
            due_color = COLORS["orange"]
        else:
            due_text = "今天到期"
            due_fg = COLORS["green_soft"]
            due_color = COLORS["green"]

        due_badge = make_badge(meta, due_text, due_fg, due_color)
        due_badge.pack(side="left", padx=(6, 0))

        ctk.CTkLabel(
            meta,
            text=format_created_at(item.get("created_at")),
            font=ui_font(9),
            text_color=COLORS["faint"],
        ).pack(side="left", padx=(8, 0))

        # 在今日页也能直接改标题/备注，不用先切到「全部计划」。
        ctk.CTkButton(
            meta,
            text="编辑",
            width=40,
            height=22,
            corner_radius=7,
            fg_color="transparent",
            hover_color=COLORS["accent_soft"],
            text_color=COLORS["faint"],
            font=ui_font(9, "bold"),
            command=lambda: self.open_edit_dialog(item),
        ).pack(side="left", padx=(8, 0))

        # 备注（只有填写了才显示）
        note = str(item.get("note", "") or "").strip()
        note_label = None
        if note:
            note_label = ctk.CTkLabel(
                body,
                text=note,
                font=ui_font(11),
                text_color=COLORS["muted"],
                anchor="w",
                justify="left",
                wraplength=600,
            )
            note_label.grid(row=2, column=0, sticky="ew", pady=(9, 0))

        # 右侧复选框
        variable = tk.BooleanVar(value=False)
        checkbox = ctk.CTkCheckBox(
            body,
            text="完成",
            variable=variable,
            onvalue=True,
            offvalue=False,
            width=76,
            checkbox_width=23,
            checkbox_height=23,
            corner_radius=7,
            border_width=2,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            border_color=COLORS["faint"],
            checkmark_color=COLORS["white"],
            text_color=COLORS["muted"],
            text_color_disabled=COLORS["faint"],
            font=ui_font(11, "bold"),
            command=lambda: self._complete_review(
                item_id=item["id"],
                due_iso=review["date"],
                variable=variable,
                checkbox=checkbox,
            ),
        )
        checkbox.grid(row=0, column=1, rowspan=3, sticky="e", padx=(18, 0))

        # 根据卡片宽度自动调整换行宽度，预留复选框的位置。
        wrap_labels = [title_label] + ([note_label] if note_label else [])
        bind_wraplength(body, wrap_labels, 110, 240)

    def _create_empty_today(self, has_completed: bool) -> None:
        """今日没有待办时显示的空状态卡片。"""
        card = ctk.CTkFrame(
            self.page,
            fg_color=COLORS["card"],
            corner_radius=18,
            border_width=1,
            border_color=COLORS["border"],
        )
        card.pack(fill="x")

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=28, pady=42)

        icon = ctk.CTkFrame(
            inner, width=62, height=62, corner_radius=31,
            fg_color=COLORS["green_soft"] if has_completed else COLORS["accent_soft"],
        )
        icon.pack()
        icon.pack_propagate(False)
        ctk.CTkLabel(
            icon,
            text="✓" if has_completed else "＋",
            font=ui_font(26, "bold"),
            text_color=COLORS["green"] if has_completed else COLORS["accent_text"],
        ).place(relx=0.5, rely=0.5, anchor="center")

        title = "今天全部完成，做得漂亮" if has_completed else "今天还没有复习内容"
        subtitle = (
            "已完成的复习会自动从今日待办中移除，可以去全部计划查看进度。"
            if has_completed
            else "添加一项背诵内容，系统会自动排好复习时间轴。"
        )

        ctk.CTkLabel(
            inner, text=title, font=ui_font(17, "bold"),
            text_color=COLORS["text"],
        ).pack(pady=(14, 0))
        ctk.CTkLabel(
            inner, text=subtitle, font=ui_font(11),
            text_color=COLORS["muted"], wraplength=420, justify="center",
        ).pack(pady=(6, 16))

        buttons = ctk.CTkFrame(inner, fg_color="transparent")
        buttons.pack()

        ctk.CTkButton(
            buttons,
            text="＋  添加背诵内容",
            width=146,
            height=38,
            corner_radius=11,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["white"],
            font=ui_font(11, "bold"),
            command=self.open_add_dialog,
        ).pack(side="left")

        if has_completed:
            ctk.CTkButton(
                buttons,
                text="查看全部计划",
                width=118,
                height=38,
                corner_radius=11,
                fg_color=COLORS["card_alt"],
                hover_color=COLORS["border"],
                text_color=COLORS["muted"],
                font=ui_font(11, "bold"),
                command=lambda: self.show_view("all"),
            ).pack(side="left", padx=(8, 0))

    # --------------------------------------------------------
    # 6.6 全部计划页
    # --------------------------------------------------------
    def _render_all(self) -> None:
        """绘制全部计划页面。"""
        self._clear_page()

        items = sorted(
            self.data["items"],
            key=lambda item: str(item.get("created_at", "")),
            reverse=True,
        )
        total = len(items)
        # 每项内容的节点数可能不同（历史数据与自定义时间轴），
        # 所以用 _item_all_done 判断，而不是写死“完成 5 个”。
        finished = sum(1 for item in items if self._item_all_done(item))
        ongoing = total - finished

        # ---------- 顶部统计条 ----------
        summary = ctk.CTkFrame(
            self.page,
            fg_color=COLORS["card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        summary.pack(fill="x", pady=(0, 18))
        summary.grid_columnconfigure(0, weight=1, uniform="summary")
        summary.grid_columnconfigure(1, weight=1, uniform="summary")
        summary.grid_columnconfigure(2, weight=1, uniform="summary")

        self._create_summary_stat(summary, 0, "全部计划", total, COLORS["text"])
        self._create_summary_stat(summary, 1, "进行中", ongoing, COLORS["accent_text"])
        self._create_summary_stat(summary, 2, "已完成", finished, COLORS["green"])

        # 两个统计块之间加细分割线。
        for column in (1, 2):
            # height=1 只是“请求高度”。配合 sticky="nsw"，
            # 它会被拉伸到和整行一样高，但不会反过来把统计卡撑高。
            divider = ctk.CTkFrame(
                summary, fg_color=COLORS["border"], width=1, height=1,
                corner_radius=0,
            )
            divider.grid(row=0, column=column, sticky="nsw", pady=16)

        # ---------- 列表标题 ----------
        section = ctk.CTkFrame(self.page, fg_color="transparent")
        section.pack(fill="x", pady=(4, 10))
        ctk.CTkLabel(
            section, text="复习时间轴", font=ui_font(16, "bold"),
            text_color=COLORS["text"], anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            section, text="每项按自己的时间轴复习", font=ui_font(10),
            text_color=COLORS["faint"], anchor="e",
        ).pack(side="right")

        # ---------- 全部计划卡片 ----------
        if not items:
            self._create_empty_all()
        else:
            for item in items:
                self._create_plan_card(item)

        ctk.CTkFrame(self.page, fg_color="transparent", height=8).pack(fill="x")

    def _create_summary_stat(
        self,
        parent: ctk.CTkFrame,
        column: int,
        label: str,
        value: int,
        color: Any,
    ) -> None:
        """创建顶部统计条中的一个数字块。"""
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=0, column=column, sticky="nsew", padx=20, pady=16)
        ctk.CTkLabel(
            box, text=str(value), font=ui_font(23, "bold"),
            text_color=color, anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            box, text=label, font=ui_font(10),
            text_color=COLORS["muted"], anchor="w",
        ).pack(anchor="w", pady=(2, 0))

    def _create_plan_card(self, item: dict[str, Any]) -> None:
        """创建一张完整计划卡片，节点来自该内容自己的时间轴。"""
        intervals = self._item_interval_days(item)
        total_nodes = len(intervals)
        done_count = self._item_done_count(item)
        all_done = done_count >= total_nodes

        card = ctk.CTkFrame(
            self.page,
            fg_color=COLORS["card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 12))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=20, pady=18)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0)

        # 标题 + 操作按钮
        title_row = ctk.CTkFrame(body, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="ew")
        title_row.grid_columnconfigure(0, weight=1)

        title_label = ctk.CTkLabel(
            title_row,
            text=item["title"],
            font=ui_font(16, "bold"),
            text_color=COLORS["text"],
            anchor="w",
            justify="left",
            wraplength=620,
        )
        title_label.grid(row=0, column=0, sticky="w")

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e", padx=(14, 0))

        progress_color = COLORS["green"] if all_done else COLORS["accent_text"]
        ctk.CTkLabel(
            actions,
            text="✓ 已完成" if all_done else f"{done_count} / {total_nodes}",
            font=ui_font(10, "bold"),
            text_color=progress_color,
            fg_color=COLORS["green_soft"] if all_done else COLORS["accent_soft"],
            corner_radius=8,
            height=24,
            width=70 if all_done else 50,
        ).pack(side="left")

        ctk.CTkButton(
            actions,
            text="编辑",
            width=44,
            height=27,
            corner_radius=8,
            fg_color="transparent",
            hover_color=COLORS["accent_soft"],
            text_color=COLORS["muted"],
            font=ui_font(10, "bold"),
            command=lambda: self.open_edit_dialog(item),
        ).pack(side="left", padx=(6, 0))

        ctk.CTkButton(
            actions,
            text="时间轴",
            width=52,
            height=27,
            corner_radius=8,
            fg_color="transparent",
            hover_color=COLORS["accent_soft"],
            text_color=COLORS["muted"],
            font=ui_font(10, "bold"),
            command=lambda: self.open_timeline_editor(item),
        ).pack(side="left", padx=(6, 0))

        ctk.CTkButton(
            actions,
            text="删除",
            width=44,
            height=27,
            corner_radius=8,
            fg_color="transparent",
            hover_color=COLORS["red_soft"],
            text_color=COLORS["faint"],
            font=ui_font(10, "bold"),
            command=lambda: self._ask_delete(item),
        ).pack(side="left", padx=(6, 0))

        # 创建时间
        meta_label = ctk.CTkLabel(
            body,
            text=(
                f"{format_created_at(item.get('created_at'))}  ·  "
                f"共 {total_nodes} 个复习节点  ·  "
                f"时间轴 {format_interval_summary(intervals)} 天"
            ),
            font=ui_font(9),
            text_color=COLORS["faint"],
            anchor="w",
        )
        meta_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # 备注
        note = str(item.get("note", "") or "").strip()
        note_label = None
        if note:
            note_label = ctk.CTkLabel(
                body,
                text=note,
                font=ui_font(11),
                text_color=COLORS["muted"],
                anchor="w",
                justify="left",
                wraplength=700,
            )
            note_label.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        # ---------- 横向时间轴（节点数量来自这一项自己的时间轴） ----------
        timeline = ctk.CTkFrame(body, fg_color="transparent")
        timeline.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        for column in range(total_nodes):
            timeline.grid_columnconfigure(column, weight=1, uniform="timeline")

        now = today_date()
        reviews_by_day = {
            review["day"]: review for review in item["reviews"]
        }

        # 节点一多，横向空间就被摊薄；超过 6 个时缩小字号和间距，
        # 保证“第 N 天 / 日期 / 状态”仍然读得清。
        compact = total_nodes > 6
        day_font = ui_font(8 if compact else 9, "bold")
        date_font = ui_font(9 if compact else 10, "bold")
        status_font = ui_font(8 if compact else 9)
        column_gap = 4 if compact else 6
        head_pady = (6, 0) if compact else (8, 0)
        tail_pady = (2, 6) if compact else (2, 8)

        for column, day in enumerate(intervals):
            review = reviews_by_day.get(day)
            due = parse_iso_date(review.get("date")) if review else None

            if review and review.get("done"):
                box_fg = COLORS["green_soft"]
                day_color = COLORS["green"]
                date_color = COLORS["green"]
                status_text = "✓ 已完成"
                status_color = COLORS["green"]
            elif due and due < now:
                overdue = (now - due).days
                box_fg = COLORS["orange_soft"]
                day_color = COLORS["orange"]
                date_color = COLORS["orange"]
                status_text = f"逾期 {overdue} 天"
                status_color = COLORS["orange"]
            elif due and due == now:
                box_fg = COLORS["accent_soft"]
                day_color = COLORS["accent_text"]
                date_color = COLORS["accent_text"]
                status_text = "今天"
                status_color = COLORS["accent_text"]
            else:
                box_fg = COLORS["card_alt"]
                day_color = COLORS["muted"]
                date_color = COLORS["text"]
                status_text = "待复习"
                status_color = COLORS["faint"]

            box = ctk.CTkFrame(timeline, fg_color=box_fg, corner_radius=10)
            box.grid(
                row=0,
                column=column,
                sticky="nsew",
                padx=(0 if column == 0 else column_gap, 0),
            )

            ctk.CTkLabel(
                box, text=f"第 {day} 天", font=day_font,
                text_color=day_color,
            ).pack(pady=head_pady)
            ctk.CTkLabel(
                box,
                text=format_timeline_date(due) if due else "—",
                font=date_font,
                text_color=date_color,
            ).pack(pady=(2, 0))
            ctk.CTkLabel(
                box, text=status_text, font=status_font,
                text_color=status_color,
            ).pack(pady=tail_pady)

        # 标题和备注随卡片宽度自动换行。
        labels_to_wrap = [title_label] + ([note_label] if note_label else [])
        bind_wraplength(body, labels_to_wrap, 150, 240)

    def _create_empty_all(self) -> None:
        """全部计划为空时的占位卡片。"""
        card = ctk.CTkFrame(
            self.page,
            fg_color=COLORS["card"],
            corner_radius=18,
            border_width=1,
            border_color=COLORS["border"],
        )
        card.pack(fill="x")

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=28, pady=44)

        icon = ctk.CTkFrame(
            inner, width=62, height=62, corner_radius=31,
            fg_color=COLORS["accent_soft"],
        )
        icon.pack()
        icon.pack_propagate(False)
        ctk.CTkLabel(
            icon, text="▤", font=ui_font(24, "bold"),
            text_color=COLORS["accent_text"],
        ).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            inner, text="还没有背诵计划", font=ui_font(17, "bold"),
            text_color=COLORS["text"],
        ).pack(pady=(14, 0))
        ctk.CTkLabel(
            inner,
            text="添加第一项内容后，这里会展示每一条复习时间轴。",
            font=ui_font(11), text_color=COLORS["muted"],
        ).pack(pady=(6, 16))

        ctk.CTkButton(
            inner,
            text="＋  添加背诵内容",
            width=146,
            height=38,
            corner_radius=11,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["white"],
            font=ui_font(11, "bold"),
            command=self.open_add_dialog,
        ).pack()

    # --------------------------------------------------------
    # 6.7 添加、完成、删除、单条时间轴
    # --------------------------------------------------------
    def _item_interval_days(self, item: dict[str, Any]) -> list[int]:
        """
        获取某一条内容自己的复习时间轴。

        新数据直接读取 interval_days；历史数据可能没有该字段，
        此时从它的 reviews 节点推导。每条任务互不影响。
        """
        review_days = sorted(
            {
                int(review["day"])
                for review in item.get("reviews", [])
                if isinstance(review.get("day"), int)
                and 1 <= int(review["day"]) <= MAX_INTERVAL_DAY
            }
        )

        intervals, _error = validate_review_intervals(
            item.get("interval_days"),
        )
        if intervals and set(intervals) == set(review_days):
            return intervals
        return review_days or list(DEFAULT_REVIEW_INTERVALS)

    def _item_base_day(self, item: dict[str, Any]) -> date:
        """
        找到某条内容“第 1 天”对应的日期。

        正常情况下直接使用 created_at 的日期；如果旧数据缺少创建时间，
        就用最早的复习日期倒推，保证调整时间轴时基准不漂移。
        """
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

    def open_add_dialog(self) -> None:
        """打开“添加背诵内容”弹窗；时间轴在弹窗内按本次内容单独设置。"""
        if self._add_dialog is not None:
            try:
                if self._add_dialog.winfo_exists():
                    self._add_dialog.lift()
                    self._add_dialog.focus_force()
                    return
            except tk.TclError:
                # 窗口可能已经被用户关闭，转而创建新的弹窗即可。
                pass
        self._add_dialog = AddItemDialog(self, self._add_item)

    def open_timeline_editor(self, item: dict[str, Any]) -> None:
        """为单条背诵内容打开时间轴调整弹窗。"""
        if self._timeline_dialog is not None:
            try:
                if self._timeline_dialog.winfo_exists():
                    self._timeline_dialog.lift()
                    self._timeline_dialog.focus_force()
                    return
            except tk.TclError:
                pass

        self._timeline_dialog = ItemTimelineDialog(
            self,
            item_title=item["title"],
            base_day=self._item_base_day(item),
            intervals=self._item_interval_days(item),
            on_save=lambda intervals: self._save_item_intervals(
                item["id"], intervals
            ),
        )

    def open_edit_dialog(self, item: dict[str, Any]) -> None:
        """打开“编辑背诵内容”弹窗，修改已经保存的标题和备注。"""
        if self._edit_dialog is not None:
            try:
                window_alive = self._edit_dialog.winfo_exists()
                same_item = self._edit_dialog.item_id == item["id"]
                if window_alive and same_item:
                    self._edit_dialog.lift()
                    self._edit_dialog.focus_force()
                    return
                if window_alive:
                    # 已经打开的是另一条内容：先关掉，避免标题和实际保存对象对不上。
                    self._edit_dialog.close()
            except tk.TclError:
                pass

        self._edit_dialog = ItemEditDialog(
            self,
            item_id=item["id"],
            initial_title=item["title"],
            initial_note=str(item.get("note", "") or ""),
            intervals=self._item_interval_days(item),
            on_save=lambda title, note: self._update_item_content(
                item["id"], title, note
            ),
        )

    def _update_item_content(self, item_id: str, title: str, note: str) -> bool:
        """
        保存某一项背诵内容的标题和备注。

        只改这两个字段，复习节点、完成状态和创建日期都原样保留；
        写文件失败时把内存改回去，避免界面上显示已修改、文件里却没变。
        """
        target_item = next(
            (item for item in self.data["items"] if item["id"] == item_id),
            None,
        )
        if target_item is None:
            self.show_toast("这条内容已经不存在，请刷新后重试", "error")
            return False

        old_title = target_item.get("title", "")
        old_note = target_item.get("note", "")

        target_item["title"] = title
        target_item["note"] = note

        if not self._save_data():
            target_item["title"] = old_title
            target_item["note"] = old_note
            self.show_toast("保存失败，请检查目录是否可写", "error")
            return False

        self._update_sidebar_stats()
        self._rerender_preserving_scroll()
        self.after(
            80,
            lambda: self.show_toast(f"「{title}」的内容已更新", "success"),
        )
        return True

    def _save_item_intervals(self, item_id: str, intervals: list[int]) -> bool:
        """
        只更新指定任务的时间轴和复习日期。

        重新生成 reviews 时，相同“第 N 天”节点的完成状态会保留；
        新节点为未完成，被移除的节点则从任务中删除。
        """
        target_item = next(
            (item for item in self.data["items"] if item["id"] == item_id),
            None,
        )
        if target_item is None:
            return False

        base_day = self._item_base_day(target_item)
        old_reviews = target_item.get("reviews", [])
        old_interval_days = target_item.get("interval_days")
        old_reviews_by_day = {
            review["day"]: review
            for review in old_reviews
            if isinstance(review.get("day"), int)
        }

        new_reviews: list[dict[str, Any]] = []
        for day in intervals:
            target_date = base_day + timedelta(days=day - 1)
            old_review = old_reviews_by_day.get(day)
            done = bool(old_review and old_review.get("done"))
            new_reviews.append(
                {
                    "day": day,
                    "date": target_date.isoformat(),
                    "done": done,
                    "completed_at": old_review.get("completed_at") if done else None,
                }
            )

        target_item["interval_days"] = list(intervals)
        target_item["reviews"] = new_reviews

        if not self._save_data():
            # 保存失败则完整恢复旧时间轴和旧节点。
            target_item["interval_days"] = old_interval_days
            target_item["reviews"] = old_reviews
            self.show_toast("时间轴保存失败，请检查目录是否可写", "error")
            return False

        self._update_sidebar_stats()
        self._rerender_preserving_scroll()
        self.after(
            80,
            lambda: self.show_toast(
                f"「{target_item['title']}」的时间轴已更新为 "
                f"第 {format_interval_summary(intervals)} 天",
                "success",
            ),
        )
        return True

    def _add_item(
        self,
        title: str,
        note: str,
        intervals: list[int],
    ) -> bool:
        """用用户在弹窗里指定的独立时间轴创建内容并保存。"""
        now = datetime.now().astimezone()
        base_day = today_date()

        # 直接把这一条内容自己的时间轴保存下来，不再依赖全局设置。
        interval_days = list(intervals)
        reviews = []
        for day in interval_days:
            # 第 N 天 = 添加当天 + (N - 1) 天。
            target = base_day + timedelta(days=day - 1)
            reviews.append(
                {
                    "day": day,
                    "date": target.isoformat(),
                    "done": False,
                    "completed_at": None,
                }
            )

        item = {
            "id": uuid.uuid4().hex,
            "title": title,
            "note": note,
            "created_at": now.isoformat(timespec="seconds"),
            "interval_days": interval_days,
            "reviews": reviews,
        }

        # 新内容放在列表最前面，全部计划页会优先显示。
        self.data["items"].insert(0, item)
        if not self._save_data():
            # 保存失败则回滚内存，避免界面显示“已添加”但文件没写进去。
            self.data["items"].remove(item)
            self.show_toast("保存失败，请检查目录是否可写", "error")
            return False

        self._update_sidebar_stats()
        self.show_view("today")
        self.after(
            80,
            lambda: self.show_toast(
                f"已为「{title}」生成 {len(interval_days)} 个复习节点",
                "success",
            ),
        )
        return True

    def _complete_review(
        self,
        item_id: str,
        due_iso: str,
        variable: tk.BooleanVar,
        checkbox: ctk.CTkCheckBox,
    ) -> None:
        """勾选后，把对应的复习节点标记为完成。"""
        if not variable.get():
            return

        target_item = None
        target_review = None
        for item in self.data["items"]:
            if item["id"] != item_id:
                continue
            for review in item["reviews"]:
                if review["date"] == due_iso:
                    target_item = item
                    target_review = review
                    break
            break

        if target_item is None or target_review is None or target_review.get("done"):
            return

        # 先修改内存，再保存；如果保存失败要恢复原状态。
        target_review["done"] = True
        target_review["completed_at"] = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )

        if not self._save_data():
            target_review["done"] = False
            target_review["completed_at"] = None
            variable.set(False)
            checkbox.configure(state="normal")
            self.show_toast("保存失败，本次完成状态未记录", "error")
            return

        # 立即禁用复选框，给用户“操作已生效”的反馈。
        try:
            checkbox.configure(state="disabled", text="已完成")
        except tk.TclError:
            pass

        title = target_item["title"]
        done_count = self._item_done_count(target_item)
        total_nodes = len(self._item_interval_days(target_item))
        if done_count >= total_nodes:
            message = f"「{title}」的 {total_nodes} 次复习全部完成！"
        else:
            # 找下一个尚未完成的节点，用于文案提示。
            next_review = next(
                (
                    review
                    for review in sorted(
                        target_item["reviews"], key=lambda r: r["day"]
                    )
                    if not review.get("done")
                ),
                None,
            )
            if next_review:
                next_date = parse_iso_date(next_review["date"])
                if next_date and next_date < today_date():
                    # 一次补做了较早的节点，但后面还有更近的逾期节点。
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

        self.show_toast(message, "success")
        self._update_sidebar_stats()

        # 延迟约 200 毫秒再重绘，让用户看见复选框变成勾选状态。
        if self._refresh_job is not None:
            try:
                self.after_cancel(self._refresh_job)
            except tk.TclError:
                pass
        self._refresh_job = self.after(220, self._rerender_preserving_scroll)

    def _ask_delete(self, item: dict[str, Any]) -> None:
        """弹出删除确认框。"""
        if self._delete_dialog is not None:
            try:
                if self._delete_dialog.winfo_exists():
                    self._delete_dialog.lift()
                    return
            except tk.TclError:
                pass

        self._delete_dialog = ConfirmDialog(
            self,
            title="删除这项计划？",
            message=(
                f"「{item['title']}」的 "
                f"{len(self._item_interval_days(item))} 个复习记录将一起删除，"
                "且无法撤销。\n"
                "如果只是暂时不想背诵，可以保留计划，不必删除。"
            ),
            on_confirm=lambda: self._delete_item(item["id"]),
        )

    def _delete_item(self, item_id: str) -> None:
        """从数据中删除指定条目并保存。"""
        index = next(
            (
                i
                for i, item in enumerate(self.data["items"])
                if item["id"] == item_id
            ),
            None,
        )
        if index is None:
            return

        removed = self.data["items"].pop(index)
        if not self._save_data():
            # 保存失败则把条目放回原位置。
            self.data["items"].insert(index, removed)
            self.show_toast("删除失败，请检查目录是否可写", "error")
            return

        self._update_sidebar_stats()
        self._rerender_preserving_scroll()
        self.show_toast(f"已删除「{removed['title']}」", "warning")

    # --------------------------------------------------------
    # 6.8 数据统计与保存
    # --------------------------------------------------------
    def _pending_tasks(self) -> list[tuple[dict[str, Any], dict[str, Any], date]]:
        """
        返回今天应该复习、但还没完成的任务。

        规则：复习日期 <= 今天 且未完成。
        这样即使某天没打开软件，漏掉的复习也会以“逾期”的形式继续出现，
        而不是被程序悄悄跳过。
        """
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

        # 先按到期日排序；同一天到期的，再按添加时间和标题排序。
        tasks.sort(key=lambda row: (row[2], str(row[0].get("created_at", "")), row[0]["title"]))
        return tasks

    def _completed_today_count(self) -> int:
        """统计今天勾选完成的数量（包括补做以前逾期节点的情况）。"""
        today_iso = today_date().isoformat()
        count = 0
        for item in self.data["items"]:
            for review in item.get("reviews", []):
                if not review.get("done"):
                    continue
                completed_at = str(review.get("completed_at", "") or "")
                if completed_at.startswith(today_iso):
                    count += 1
        return count

    def _item_done_count(self, item: dict[str, Any]) -> int:
        """统计某一项内容已经完成多少个复习节点。"""
        return sum(1 for review in item.get("reviews", []) if review.get("done"))

    def _item_all_done(self, item: dict[str, Any]) -> bool:
        """判断某一项内容的全部时间轴节点是否都已完成。"""
        total_nodes = len(self._item_interval_days(item))
        return total_nodes > 0 and self._item_done_count(item) >= total_nodes

    def _update_sidebar_stats(self) -> None:
        """刷新左侧“今日进度”卡片。"""
        pending = len(self._pending_tasks())
        completed = self._completed_today_count()
        total = pending + completed
        percent = int(round(completed / total * 100)) if total else 0

        self.stats_ratio.configure(text=f"{completed} / {total}")
        self.stats_percent.configure(text=f"{percent}%")
        self.stats_bar.set(completed / total if total else 0)

        if total == 0:
            detail = "今天暂无复习安排"
        elif pending == 0:
            detail = "今日任务全部完成"
        else:
            detail = f"还有 {pending} 项待完成"
        self.stats_detail.configure(text=detail)

    def _save_data(self) -> bool:
        """保存数据，并同步左下角的保存状态文字。"""
        success = self.store.save(self.data)
        now_text = datetime.now().strftime("%H:%M")
        if success:
            self.save_label.configure(
                text=f"●  已自动保存 {now_text}",
                text_color=COLORS["green"],
            )
        else:
            self.save_label.configure(
                text="●  保存失败",
                text_color=COLORS["red"],
            )
        return success

    def _rerender_preserving_scroll(self) -> None:
        """重新绘制当前页面，并尽量保持原来的滚动位置。"""
        self._refresh_job = None

        try:
            scroll_position = self.page._parent_canvas.yview()[0]  # noqa: SLF001
        except (AttributeError, tk.TclError):
            scroll_position = 0.0

        if self.current_view == "today":
            self._render_today()
        else:
            self._render_all()
        self._update_sidebar_stats()

        # 等布局更新完再恢复滚动位置，避免跳动。
        def _restore() -> None:
            try:
                self.page._parent_canvas.yview_moveto(scroll_position)  # noqa: SLF001
            except (AttributeError, tk.TclError):
                pass

        self.after(10, _restore)

    def _refresh_today_at_midnight(self) -> None:
        """刷新日期判断，让长期开着的窗口也能进入新的一天。"""
        self.show_view(self.current_view)
        self.show_toast("已刷新今日任务", "success")

    # --------------------------------------------------------
    # 6.9 外观切换和提示条
    # --------------------------------------------------------
    def _change_appearance(self, label: str) -> None:
        """切换浅色/深色/跟随系统，并把偏好写入 JSON。"""
        mode = APPEARANCE_MODES.get(label, "system")
        self.appearance_mode = mode
        # 同步下拉框变量：即使以后从代码里调用本方法，显示也保持一致。
        self.appearance_choice.set(APPEARANCE_LABELS[mode])
        ctk.set_appearance_mode(mode)

        self.data.setdefault("settings", {})["appearance"] = mode
        self._save_data()

    def show_toast(self, message: str, kind: str = "success") -> None:
        """
        在右下角显示一条短暂的提示。

        kind 支持 success / warning / error，只影响颜色，不影响布局。
        """
        if self._toast_job is not None:
            try:
                self.after_cancel(self._toast_job)
            except tk.TclError:
                pass
            self._toast_job = None

        # 每次显示都新建一个浮层，避免旧控件残留。
        if hasattr(self, "_toast") and self._toast.winfo_exists():
            self._toast.destroy()

        if kind == "error":
            fg_color = COLORS["red_soft"]
            text_color = COLORS["red"]
            dot = "●"
        elif kind == "warning":
            fg_color = COLORS["orange_soft"]
            text_color = COLORS["orange"]
            dot = "●"
        else:
            fg_color = COLORS["green_soft"]
            text_color = COLORS["green"]
            dot = "✓"

        toast = ctk.CTkFrame(
            self,
            fg_color=fg_color,
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        toast.place(relx=1.0, rely=1.0, anchor="se", x=-26, y=-24)
        toast.lift()

        ctk.CTkLabel(
            toast, text=dot, font=ui_font(12, "bold"),
            text_color=text_color,
        ).pack(side="left", padx=(14, 6), pady=10)
        ctk.CTkLabel(
            toast, text=message, font=ui_font(11, "bold"),
            text_color=COLORS["text"], wraplength=360, justify="left",
        ).pack(side="left", padx=(0, 14), pady=10)

        self._toast = toast
        self._toast_job = self.after(3000, self._hide_toast)

    def _hide_toast(self) -> None:
        """隐藏提示条。"""
        self._toast_job = None
        if hasattr(self, "_toast"):
            try:
                self._toast.destroy()
            except tk.TclError:
                pass

    # --------------------------------------------------------
    # 6.10 关闭程序
    # --------------------------------------------------------
    def _on_close(self) -> None:
        """关闭前再保存一次，然后销毁窗口。"""
        self.store.save(self.data)
        self.destroy()


# ============================================================
# 七、启动入口
# ============================================================
def main() -> None:
    """设置全局主题并启动主循环。"""
    # “system” 会让 customtkinter 检测 Windows 当前的浅色/深色设置。
    # 如果用户在应用内改过外观，ReviewApp 初始化时会用保存的偏好覆盖它。
    ctk.set_appearance_mode("system")

    # 这里使用默认主题作为底层兜底；界面上大部分颜色都由 COLORS 明确指定。
    ctk.set_default_color_theme("blue")

    app = ReviewApp()
    app.mainloop()


if __name__ == "__main__":
    # 只有直接运行 app.py 时才启动界面；
    # 被其他脚本 import 时不会自动打开窗口。
    main()
