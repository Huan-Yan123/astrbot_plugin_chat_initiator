# 主动聊天插件 (Chat Initiator)

让 AstrBot 像真人一样在群里/私聊里主动冒泡，随机或定时发起聊天。

## 功能

- **随机触发**：在活跃时段内，按可配置的随机间隔主动发起聊天
- **定时触发**：在指定时间点（HH:MM 或 Cron 表达式）精准触发
- **智能读历史**：读取最近 N 轮对话，AI 判断是否适合延续话题
- **文字+表情包**：按概率随机发文字或表情包，表情包优先匹配已有的表情包小偷库存
- **人设连贯**：沿用当前会话选择的人设和模型，不突兀
- **防打扰**：AI 判断当前是否适合插话（吵架/严肃事务时自动 SKIP）
- **黑白名单**：群聊和私聊分别支持黑白名单
- **活跃时间段**：只在指定时间段内工作，半夜不扰民
- **冷却时间**：两次触发之间强制间隔，防止刷屏

## 配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| random_trigger_enabled | true | 是否开启随机触发 |
| random_min_minutes | 20 | 随机触发最小间隔（分钟） |
| random_max_minutes | 180 | 随机触发最大间隔（分钟） |
| schedule_trigger_enabled | false | 是否开启定时触发 |
| schedule_times | 08:00,12:00,18:00,22:00 | 定时时间点，HH:MM 格式，逗号分隔 |
| schedule_cron | 0 8,12,18,22 * * * | Cron 表达式，schedule_times 为空时生效 |
| active_start_hour | 9 | 活跃开始时间（0-23） |
| active_end_hour | 24 | 活跃结束时间（0-24） |
| cool_down_minutes | 60 | 冷却时间（分钟） |
| enable_group_chat | true | 是否在群聊中触发 |
| enable_private_chat | false | 是否在私聊中触发 |
| group_whitelist / group_blacklist | 空 | 群聊白/黑名单，逗号分隔 |
| user_whitelist / user_blacklist | 空 | 用户白/黑名单，逗号分隔 |
| text_probability | 70 | 文字聊天概率（%），剩余为表情包 |
| max_history_rounds | 20 | 读取历史对话轮数（1-50） |
| require_topic_relevance | true | 无历史时优先发表情包而非强行文字 |
| new_topic_prompt | 见配置 | 无历史时生成新话题的提示词 |
| emoji_search_word | 开心 | 表情包搜索关键词，逗号分隔多个 |
| check_disturbing | true | 发送前 AI 判断是否打扰 |

## 注意事项

- 表情包功能依赖「表情包小偷」插件，需确保已安装并启用
- 插件无命令，安装启用后后台自动运行
- 私聊模式默认关闭，如需开启请手动勾选 `enable_private_chat` 并设置白名单
- 建议冷却时间不低于 30 分钟，避免刷屏
