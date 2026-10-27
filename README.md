# Dafeiyu · 给 LLM Agent 的三层记忆与轻量情绪

> **一句话**：让 agent **记得住事、会淡忘、还会有点心情** —— 不改模型、不接向量库、不依赖任何第三方客户端。

---

## 这是什么

大多数 LLM agent 有两个毛病：

1. **要么全忘**（每次会话从零开始），**要么全记**（把所有东西塞进上下文，越用越慢越贵）；
2. **永远同一个语气**，不管刚被夸过还是刚被骂过。

这个项目提供两个可以独立也可组合的**纯本地**模块：

| 模块 | 解决什么 | 依赖 |
|---|---|---|
| **记忆子系统** `core/memory.py` | 写入时算「惊讶度」、按查询检索、随时间淡忘、去重与巩固 | 仅 SQLite |
| **情绪层** `core/mood.py` + `core/needs.py` | 精力/心情两个标量，由**需求缺口**内生驱动，随时间与事件漂移 | 无 |

三种接入方式：**命令行**、**HTTP API**、**MCP server**（可直接挂给支持 MCP 的 agent）。

## 三层记忆

常见做法各有一个天花板：

- **把索引塞进系统提示词**：永远生效、零调用成本，但索引是**静态的**——跟"这一句问的是什么"无关。记忆一多，只能靠"重要+新鲜"挑，挑不出该想起的那条。
- **纯检索**：能按问题找，但**要模型主动查**，忘了查就等于失忆。

所以这里分层，各管一段：

```
常驻层   少量、稳定的事实，每轮注入（不依赖检索）
长尾层   大量事件细节，按需检索（图扩散 + 词法 + 权重/分区/多样性）
短会话层 进行中的话题与印象，随唤醒带出
```

判据只有一句：**「下次还成立吗？」** 成立 → 常驻；只这一次 → 长尾；只是这几天的状态 → 短会话。

## 轻量情绪

情绪的本质不是"好/坏"这个数字，而是**期望与现实的落差**。所以不是"事件 → 加减分"，而是：

```
需求缺口（社交 / 新鲜感 / 休息） → 精力 & 心情 → 语气 + 回复节奏
```

- 满意度随时间自然下降 → 缺口变大 → **即使一整天没人说话，状态也在自己走**
- 满足一个需求，下一个缺口就浮上来（社交满足了，"无聊"更显眼）
- **只影响表达**：回得快不快、话多不多、语气冷不冷；**不参与事实判断，也不改变"要不要回答你"**

## 快速开始

```bash
# 1. 端到端演示（写入 → 检索 → 巩固 → 遗忘）
python3 cli.py demo

# 2. 用起来
python3 cli.py add "用户在学 Rust，想写命令行工具" --source owner --level important --tags 编程,Rust
python3 cli.py search "他在学什么" --top 5

# 3. 自测（54 项）
python3 tests/test_memory.py
python3 tests/test_mood.py
python3 tests/test_needs.py

# 4. HTTP API
python3 server.py --port 8730
curl -s -X POST localhost:8730/add    -H 'content-type: application/json' -d '{"text":"用户喜欢冰美式"}'
curl -s -X POST localhost:8730/search -H 'content-type: application/json' -d '{"query":"咖啡"}'

# 5. 情绪守护（定期衰减、按活动日志增量推断事件）
python3 moodd.py
```

接入 MCP（给支持 MCP 的 agent）：

```bash
npm install
# 在 agent 的 MCP 配置里指向：
#   command: node
#   args: ["<仓库绝对路径>/mcp-server.mjs"]
# 暴露工具：dafeiyu_search / dafeiyu_write / dafeiyu_stats
```

## 配置

全部可用环境变量覆盖，默认相对仓库自身：

| 变量 | 默认 | 说明 |
|---|---|---|
| `DAFEIYU_HOME` | 仓库根 | 数据根目录 |
| `DAFEIYU_DB` | `data/memory.db` | 记忆库 |
| `DAFEIYU_MOOD_STATE` | `data/mood.json` | 精力/心情 |
| `DAFEIYU_NEEDS_STATE` | `data/needs.json` | 需求满意度 |
| `DAFEIYU_TOKEN` | 空 | HTTP/MCP 令牌（设置后需 `Authorization: Bearer`） |
| `DAFEIYU_CHAT_STATE` | `data/chat-state` | **可选**：与聊天侧交换状态行的目录 |

算法参数集中在 [`core/config.py`](core/config.py)：写入权重、检索权重、遗忘半衰期、去重阈值、多样性衰减、编码位定义。

## 设计取舍（先说清楚）

- **没有真向量**：语义相似度用 TF-IDF 余弦 + 字符二元组 + 图扩散近似，零外部服务。接口留好了，换成 embedding 只需改 [`core/text.py`](core/text.py) 的一个函数。
- **巩固是确定性的**：相似记忆合并成一条抽象记忆（共享内容词 ≥2 且重叠 ≥25%），不是 LLM 摘要。
- **不做世界模拟**：没有岛屿、天气、经济、日程。那些对"回答质量"是负资产。
- **没有主观体验**：这里只有变量和它们对输出的影响。`mood` 变低不等于"难过"。
- **不绑定任何聊天平台**：核心与传输无关；接不接聊天软件、接哪个，由使用者决定。

## 目录

```
core/
  config.py    全部可调参数
  text.py      分词 / 相似度 / 6 位结构编码（换 embedding 只改这里）
  store.py     SQLite：节点 / 边 / 倒排 / idf
  memory.py    编码 · 巩固 · 检索 · 遗忘 · 维护
  mood.py      精力 + 心情（衰减、事件、渲染）
  needs.py     需求缺口（内生漂移的来源）
  paths.py     路径解析（全部可环境变量覆盖）
server.py      HTTP API
mcp-server.mjs MCP 工具层（stdio）
moodd.py       情绪守护（定期 tick）
cli.py         命令行
tests/         54 项自测
```

## 路线图

- [x] 记忆闭环（编码/存储/巩固/检索/遗忘/维护）
- [x] 去重、容量淘汰、反刍抑制、编码多样性
- [x] 精力/心情 + 需求缺口
- [x] HTTP API / MCP / CLI
- [ ] 真向量检索（可插拔 embedding）
- [ ] 情绪对记忆的偏置（心情影响记住什么、想起什么）
- [ ] 更多需求维度与个体差异

## 边界声明

本仓库只包含原创实现：**不包含任何第三方角色设定、他人文档内容，也不包含对特定客户端软件的修改或注入方案。**

## License

MIT，见 [LICENSE](LICENSE)。

---

## English

**Dafeiyu** gives an LLM agent a **three-layer memory** and a **lightweight affect layer** — local only, no vector DB, no third-party client.

- **Memory**: surprise-weighted encoding, graph + lexical retrieval, exponential forgetting, dedup & consolidation, diversity control. SQLite only.
- **Affect**: two scalars (energy, mood) driven by **need deficits** (social / novelty / rest) that decay on their own — the agent's state drifts even when nobody talks to it. It shapes *tone and pacing only*, never facts, and never whether it answers.
- **Interfaces**: CLI, HTTP API, MCP server (stdio).

```bash
python3 cli.py demo
python3 tests/test_memory.py && python3 tests/test_mood.py && python3 tests/test_needs.py
python3 server.py --port 8730
python3 moodd.py
```

Semantic similarity is approximated offline (TF-IDF + character bigrams + graph diffusion); swap in embeddings by editing one function in `core/text.py`. MIT licensed.
