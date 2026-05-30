import asyncio
import json
import os
import random
import re
import time
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register
from astrbot.core.message.components import Plain, Image
from astrbot.core.message.message_event_result import MessageChain


@register(
    "astrbot_plugin_chat_initiator",
    "mx",
    "随机/定时主动聊天插件，可读取历史和当前人设，也可调用表情包小偷库存发图",
    "1.0.2",
)
class ChatInitiatorPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        self._task: asyncio.Task | None = None
        self._last_trigger: dict[str, float] = {}
        self._next_random_ts: dict[str, float] = {}
        self._running = False

    async def initialize(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("主动聊天插件已启动")

    async def terminate(self):
        try:
            self._running = False
            if self._task:
                self._task.cancel()
                try:
                    await self._task
                except BaseException:
                    pass
            logger.info("主动聊天插件已停止")
        except BaseException:
            pass

    # ── 配置读取工具 ──

    def _cfg(self, key: str, default: Any = None) -> Any:
        try:
            return self.config.get(key, default)
        except Exception:
            return default

    def _split_ids(self, value: str) -> set[str]:
        return {x.strip() for x in str(value or "").replace("\n", ",").split(",") if x.strip()}

    # ── 活跃时间段 ──

    def _active_now(self) -> bool:
        h = time.localtime().tm_hour
        start = int(self._cfg("active_start_hour", 9))
        end = int(self._cfg("active_end_hour", 24))
        # 输入校验：限制在 0-24
        start = max(0, min(24, start))
        end = max(0, min(24, end))
        if start == end:
            return True
        if start < end:
            return start <= h < end
        return h >= start or h < end

    # ── 冷却时间 ──

    def _cooldown_ok(self, session: str) -> bool:
        minutes = int(self._cfg("cool_down_minutes", 60) or 60)
        minutes = max(0, min(1440, minutes))
        last = self._last_trigger.get(session, 0)
        return time.time() - last >= minutes * 60

    def _mark_triggered(self, session: str):
        self._last_trigger[session] = time.time()
        self._next_random_ts.pop(session, None)

    # ── session 解析 ──

    def _parse_session_id(self, umo: str) -> str:
        parts = str(umo).split(":")
        return parts[-1] if parts else str(umo)

    def _is_group_session(self, umo: str) -> bool:
        return "Group" in str(umo) or "group" in str(umo)

    def _is_private_session(self, umo: str) -> bool:
        return "Friend" in str(umo) or "private" in str(umo) or "Private" in str(umo)

    # ── 黑白名单校验 ──

    def _target_allowed(self, umo: str) -> bool:
        sid = self._parse_session_id(umo)
        if self._is_group_session(umo):
            if not bool(self._cfg("enable_group_chat", True)):
                return False
            wl = self._split_ids(self._cfg("group_whitelist", ""))
            bl = self._split_ids(self._cfg("group_blacklist", ""))
        elif self._is_private_session(umo):
            if not bool(self._cfg("enable_private_chat", False)):
                return False
            wl = self._split_ids(self._cfg("user_whitelist", ""))
            bl = self._split_ids(self._cfg("user_blacklist", ""))
        else:
            return False
        if wl and sid not in wl and umo not in wl:
            return False
        if sid in bl or umo in bl:
            return False
        return True

    # ── 收集可用会话 ──

    async def _collect_sessions(self) -> list[str]:
        sessions: set[str] = set()
        try:
            convs = await self.context.conversation_manager.get_conversations()
            for conv in convs:
                umo = getattr(conv, "user_id", "") or ""
                if umo:
                    sessions.add(str(umo))
        except Exception as e:
            logger.warning(f"主动聊天读取会话失败: {e}")
        return [s for s in sessions if self._target_allowed(s)]

    # ── 主循环 ──

    async def _loop(self):
        await asyncio.sleep(10)
        while self._running:
            try:
                if self._active_now():
                    sessions = await self._collect_sessions()
                    random.shuffle(sessions)
                    for session in sessions:
                        if await self._should_trigger(session):
                            await self._trigger(session, "random_or_schedule")
                            break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"主动聊天循环异常: {e}", exc_info=True)
            await asyncio.sleep(60)

    # ── 判断是否触发 ──

    async def _should_trigger(self, session: str) -> bool:
        if not self._cooldown_ok(session):
            return False
        now = time.time()
        # 随机触发
        if bool(self._cfg("random_trigger_enabled", True)):
            if session not in self._next_random_ts:
                min_m = int(self._cfg("random_min_minutes", 20) or 20)
                max_m = int(self._cfg("random_max_minutes", 180) or 180)
                min_m = max(1, min_m)
                max_m = max(min_m, max_m)
                self._next_random_ts[session] = now + random.randint(min_m, max_m) * 60
            if now >= self._next_random_ts[session]:
                return True
        # 定时触发
        if bool(self._cfg("schedule_trigger_enabled", False)):
            if self._match_schedule():
                return True
        return False

    # ── 定时匹配：支持 schedule_times（HH:MM 列表）和 schedule_cron（简易cron） ──

    def _match_schedule(self) -> bool:
        # 优先读 schedule_times，回退到 schedule_cron
        times_str = str(self._cfg("schedule_times", "") or "")
        cron_str = str(self._cfg("schedule_cron", "") or "")
        now = time.localtime()
        cur_time = f"{now.tm_hour:02d}:{now.tm_min:02d}"

        # 模式1：schedule_times（如 08:00,12:00,18:00,22:00）
        if times_str:
            allowed = {x.strip() for x in times_str.split(",") if x.strip()}
            if cur_time in allowed:
                return True

        # 模式2：简易 cron（支持 0 8,12,18,22 * * * 格式）
        if cron_str:
            return self._match_simple_cron(cron_str, now)

        return False

    def _match_simple_cron(self, cron_expr: str, now: time.struct_time) -> bool:
        """仅解析 5 段 cron: minute hour day_of_month month day_of_week"""
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return False
        try:
            return (
                self._cron_field_match(parts[0], now.tm_min, 0, 59) and
                self._cron_field_match(parts[1], now.tm_hour, 0, 23) and
                self._cron_field_match(parts[2], now.tm_mday, 1, 31) and
                self._cron_field_match(parts[3], now.tm_mon, 1, 12) and
                self._cron_field_match(parts[4], now.tm_wday + 1, 1, 7)  # tm_wday: 0=Mon, cron: 0=Sun
            )
        except Exception:
            return False

    @staticmethod
    def _cron_field_match(field: str, value: int, vmin: int, vmax: int) -> bool:
        """匹配单个 cron 字段，支持 *、逗号、连字符、斜杠"""
        if field == "*":
            return True
        for part in field.split(","):
            part = part.strip()
            step = 1
            if "/" in part:
                part, step_str = part.split("/", 1)
                step = int(step_str)
            if "-" in part:
                lo, hi = part.split("-", 1)
                lo, hi = int(lo), int(hi)
                if lo <= value <= hi and (value - lo) % step == 0:
                    return True
            elif part == "*":
                if (value - vmin) % step == 0:
                    return True
            else:
                if int(part) == value:
                    return True
        return False

    # ── 读取历史 ──

    async def _get_history(self, session: str) -> list[dict]:
        rounds = int(self._cfg("max_history_rounds", 20) or 20)
        rounds = max(1, min(50, rounds))
        limit = rounds * 2
        try:
            cid = await self.context.conversation_manager.get_curr_conversation_id(session)
            if not cid:
                return []
            conv = await self.context.conversation_manager.get_conversation(session, cid)
            raw = getattr(conv, "history", "[]") if conv else "[]"
            hist = json.loads(raw or "[]")
            if isinstance(hist, list):
                return hist[-limit:]
        except Exception as e:
            logger.debug(f"主动聊天读取历史失败 {session}: {e}")
        return []

    # ── 生成文字 ──

    async def _generate_text(self, session: str, history: list[dict]) -> str:
        prov = self.context.get_using_provider(session)
        if not prov:
            return "突然想起来，今天过得怎么样"
        prompt = (
            "你正在主动发起聊天。请根据当前选择的人设、当前时间和最近历史对话，生成一句自然的开场。"
            "如果历史适合延续，就接着聊；如果不适合，就开一个新话题；如果可能打扰，就只输出 SKIP。"
            "要求：短句，像日常聊天，不要解释，不要说自己是什么插件。"
        )
        if bool(self._cfg("check_disturbing", True)):
            prompt += "发送前先判断是否打扰，对方在忙、吵架、严肃事务时输出 SKIP。"
        # require_topic_relevance：要求历史相关，无历史时引导发新话题或表情
        if bool(self._cfg("require_topic_relevance", True)):
            if not history:
                prompt += "当前无历史对话，请基于我的当前人设和当前时间生成一个自然有趣的新话题开场白。"
        else:
            prompt += str(self._cfg("new_topic_prompt", "基于我的当前人设和当前时间，生成一个自然、有趣的聊天开场白，不要说'你好'或'在吗'。"))
        if not history:
            prompt += str(self._cfg("new_topic_prompt", "随便发起一个自然的新话题。"))
        resp = await prov.text_chat(prompt=prompt, contexts=history, session_id=session)
        text = str(getattr(resp, "completion_text", "") or getattr(resp, "text", "") or resp).strip()
        text = text.strip('"“”`')
        return text

    # ── 表情包小偷集成 ──

    def _find_stealer(self):
        try:
            star_map = getattr(self.context, "_star_manager", None)
            stars = getattr(star_map, "stars", None) or getattr(star_map, "star_insts", None) or []
            for s in stars:
                cls_name = s.__class__.__name__.lower()
                mod_name = s.__class__.__module__.lower()
                if mod_name.startswith("astrbot_plugin_stealer") or cls_name.find("stealer") >= 0:
                    return s
        except Exception:
            pass
        return None

    async def _send_emoji_fallback(self, session: str) -> bool:
        words = [x.strip() for x in str(self._cfg("emoji_search_word", "开心") or "开心").split(",") if x.strip()]
        query = random.choice(words or ["开心"])
        stealer = self._find_stealer()
        try:
            if stealer and hasattr(stealer, "db_service") and hasattr(stealer, "emoji_selector"):
                total = stealer.db_service.count_total() if hasattr(stealer.db_service, "count_total") else 0
                if total > 0:
                    idx = stealer.db_service.get_index_cache_readonly()
                else:
                    idx = stealer.cache_service.get_index_cache_readonly() if hasattr(stealer, "cache_service") else None
                if idx is None:
                    return False
                results = await stealer.emoji_selector.smart_search(query, limit=5, idx=idx, event=None)
                exists = [r for r in results if r and os.path.exists(r[0])]
                if exists:
                    path = random.choice(exists)[0]
                    with open(path, "rb") as f:
                        import base64
                        b64 = base64.b64encode(f.read()).decode()
                    await self.context.send_message(session=session, message_chain=MessageChain([Image.fromBase64(b64)]))
                    return True
        except Exception as e:
            logger.warning(f"主动聊天调用表情包小偷失败: {e}")
        return False

    # ── 触发主逻辑 ──

    async def _trigger(self, session: str, reason: str):
        try:
            if not self._cooldown_ok(session):
                return
            text_probability = int(self._cfg("text_probability", 70) or 70)
            text_probability = max(0, min(100, text_probability))
            send_text = random.randint(1, 100) <= text_probability
            history = await self._get_history(session)

            # require_topic_relevance：无历史时降低文字概率
            if bool(self._cfg("require_topic_relevance", True)) and not history:
                send_text = False

            if send_text:
                text = await self._generate_text(session, history)
                if text and text.upper() != "SKIP":
                    await self.context.send_message(session=session, message_chain=MessageChain([Plain(text)]))
                    self._mark_triggered(session)
                    return

            if await self._send_emoji_fallback(session):
                self._mark_triggered(session)
                return

            # 表情包失败时再尝试文字
            if not send_text:
                text = await self._generate_text(session, history)
                if text and text.upper() != "SKIP":
                    await self.context.send_message(session=session, message_chain=MessageChain([Plain(text)]))
                    self._mark_triggered(session)
        except Exception as e:
            logger.error(f"主动聊天触发失败 {session}: {e}", exc_info=True)
