# 技术设计文档 — 古籍智能校勘系统

> 版本：v1.0（2026-10-02）。架构与选型的唯一事实来源，改动先改本文档。

## 1. 总体架构（对应赛题大纲"解决方案设计-系统架构设计"）

```
┌─────────────────────────────────────────────────────┐
│ 展示层  Vue 3 + Vite（Home / Collation / History）    │
│         Pinia 状态管理 · opencc-js 繁简转换            │
├─────────────────────────────────────────────────────┤
│ 应用层  Python + FastAPI（server/，BFF 薄层）          │
│         校验 · Prompt 组装 · 限流 · 密钥托管           │
├─────────────────────────────────────────────────────┤
│ 算法层  大模型 API（校勘/译文/释义，可插拔）            │
│         OCR API（图片→文本，可插拔）                   │
│         规则引擎（置信度修正、校勘记体例模板）           │
├─────────────────────────────────────────────────────┤
│ 数据层  无服务端持久化（无状态）；导出文件前端生成       │
└─────────────────────────────────────────────────────┘
```

**为什么是薄 BFF 而不是直连大模型**：密钥不能进前端包；Prompt 与模型切换要可服务端控制；限流和超时保护演示稳定性；同时为后续接国产模型合规审查留口子。

## 2. 技术选型（对应大纲"技术选型依据"，每项都要能讲出与学科的适配理由）

| 层 | 选型 | 理由（写进技术方案的口径） |
|---|---|---|
| 前端框架 | Vue 3 + Vite（**不重构**，沿用现有） | 现有双栏校勘台、竖排繁体渲染已成型；8 天工期不允许换框架 |
| 状态管理 | Pinia | 已安装未启用；用于上传文本/校勘结果/历史跨页传递，消灭硬编码 |
| 繁简转换 | opencc-js（已有） | 文献工具必备，客户端零成本 |
| 后端 | Python + FastAPI | 阶段二起算法层变厚（RAG/微调/评测全在 Python 生态），一步到位避免中期迁移；只做薄 BFF 时心智成本同样低（详见 ROADMAP §3） |
| 大模型 | 通义千问 qwen-max/qwen-plus（OpenAI 兼容模式） | 古文语料覆盖在国产模型里属第一梯队；OpenAI 兼容接口便于切换 |
| 备用模型 | DeepSeek（deepseek-chat） | 同为 OpenAI 兼容接口，环境变量一键切换，防止单点故障影响演示 |
| OCR | 百度智能云 OCR 高精度版 | 有古籍/竖排优化，REST 接入 1 天内完成；不自研 |
| 校勘类型判定 | 大模型结构化输出 + 规则后校验 | 模型给类型与置信度，规则引擎（形近字表、通假字表命中）修正置信度 |
| 测试 | Vitest（前端校验/解析层）+ pytest（后端 schema 与模板）+ 手动主流程 | 测试只覆盖最易炸的 JSON schema 校验与体例生成；命令：`npm test`、`.venv/Scripts/python -m pytest server/tests` |

**前端不重构的结论**：现有 `CollationView.vue` 交互即参赛作品的核心亮点（人机协同+留痕），UI 不重做；改造只发生在"数据来源"——从组件内硬编码改为 Pinia store + API。

## 3. 前端改造范围（最小侵入清单）

| 文件 | 改动 |
|---|---|
| `src/stores/collation.js`（新增） | state：sourceText、collationItems、translation、history、loading/error；actions：submitText、accept/reject、acceptAll/rejectAll、exportNote |
| `src/api/client.js`（新增） | fetch 封装：baseURL 读 `import.meta.env.VITE_API_BASE`，统一错误处理与 30s 超时 |
| `src/views/HomeView.vue` | "开始校勘"→ 调 store.submitText（粘贴路径先走通；文件 .txt 读取后同路径）→ 成功跳转 /collation |
| `src/views/CollationView.vue` | 删除硬编码 originalData/collationItems/translationText，改为 store 渲染；新增 loading / 空态 / API 错误态；校勘卡片加"类型"徽标（讹/衍/脱/通假/异文） |
| `src/components/TranslatorWidget.vue` | mockDict 换成 POST /api/v1/translate |
| `src/utils/collationNote.js`（新增） | 校勘记体例生成器（见 §6） |
| `.env.example` | `VITE_API_BASE=http://localhost:3001` |

不改：路由、样式体系、opencc 转换逻辑、About 页。
例外（实施时发现确有问题才动，共三处）：工作台 `.workspace-container` 用 `height: 100vh` 套在
顶栏与 `main-content` 内边距之内，会把工具栏挤出首屏、加载/错误状态屏也偏出可视区，
改为按可用高度计算；`.btn-start` 的 hover `translateY` 会让元素在悬停时持续位移，
触发自动化点击的稳定性重试，改为阴影反馈；`HistoryView.vue` 原本是带 2023 年假数据的脚手架、
「查看报告」按钮**没绑任何事件**（评委一点就露馅），改为展示**本次会话**的真实校勘结果并接上跳转，
假数据删除（跨会话历史仍需阶段二的持久化，见 PRD §4「明确不做」）。

**实施状态（2026-10-08）**：上表除 `TranslatorWidget.vue` 外均已落地——该组件的 `mockDict`
仍待 F6 接入 `POST /api/v1/translate`。另记三处实现取舍：
`src/api/client.js` 的前端超时取 35s（比后端的 30s 略长），让后端先返回带明确 code 的
`LLM_TIMEOUT`，用户看到的是"模型超时"而不是笼统的"请求超时"；
`src/stores/collation.js` 把「置信度 < 0.7 不参与全部采纳」实现为 `acceptAll` 只覆盖高置信条目，
低置信条目仍可单独采纳。

**文本分段流水线（2026-10-09 增补）**：新增 `src/utils/textChunks.js`，`src/stores/collation.js`
的 `submitText` 改为分段并发流水线（详见 PRD §4「文本分段提交」）。要点：

- 切分按**句读边界**（。！？；换行，过长时退到逗号/顿号），不重叠，保证首尾相接、不丢字；
- 并发度 3，段数上限 50，段大小 = max(100 字, 全文/50)；单次调用硬性总时限 60s
  （`server/config.py` 的 `REQUEST_TIMEOUT_S`，前端超时取 65s 让后端先报明确错误码）；
- **每段返回即调 `mergeCollationItems` 刷新 `items`**，所以第一段到货就可见——这是"一部分就出来一部分"
  的实现点；视图据此用 `showsWorkspace`（有结果即可）而非 `isReady`（全部完成）来切换显示；
- 段内 `offset` 由 `rebaseItems` 加上该段起点搬到全文坐标系；跨段重复建议按
  「类型+原文+建议」去重；
- 引入运行代次号 `activeRun` 作废过期结果，避免「重新开始」之后迟到的分段响应把工作台又填上；
- 某段失败时**保留已到货结果**并把完成进度写进错误消息，不清空用户已看到的内容；
- 草稿存 `sessionStorage`（键 `guji:collation-draft:v1`），刷新/切页不丢工作。
  注意这只是浏览器本地暂存，**不是服务端持久化**，与 PRD §4「明确不做」不冲突。

## 4. 后端结构（Python + FastAPI）

```
server/
  main.py             # FastAPI 入口：CORS、路由挂载、统一异常处理
  routers/
    ocr.py            # POST /api/v1/ocr
    collate.py        # POST /api/v1/collate
    translate.py      # POST /api/v1/translate
    export_note.py    # POST /api/v1/export/collation-note
    health.py         # GET  /api/v1/health
  services/
    llm.py            # OpenAI 兼容客户端；LLM_PROVIDER=qwen|deepseek 切换
    ocr.py            # 百度 OCR access_token 缓存 + 调用
    confidence.py     # 置信度规则修正（形近字表/通假字表命中）
    note_template.py  # 校勘记体例模板生成（纯规则，不调模型）
  prompts/            # Prompt 资产：按文件管理、带版本号（见 §5）
    collate_v1.md        # 保留，供回归对比
    collate_v2.md        # 当前生效（收紧 suggested 契约，见 §5）
    translate_text_v1.md
    explain_v1.md
    regression/       # Prompt 回归集：固定测试文本 + 期望要点
  utils/
    schemas.py        # pydantic 模型：请求校验 + 模型输出校验
    rate_limit.py     # 简易内存限流（30 req/min/IP）
requirements.txt      # fastapi, uvicorn, pydantic, httpx
```

- 环境变量：`LLM_PROVIDER`、`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`、`OCR_API_KEY`、`OCR_SECRET_KEY`、`PORT`（默认 3001，与 API.md 约定一致）。
- Prompt 与端点映射：`collate_v2.md` → `POST /api/v1/collate`（校勘结果与白话译文一次返回）；`translate_text_v1.md` → `/collate` 的译文子 Prompt（`options.produceTranslation=true` 时拼入主调用，**无独立翻译端点**）；`explain_v1.md` → `POST /api/v1/translate`（划词释义）。
- 运行：依赖装在独立虚拟环境（`python -m venv .venv && pip install -r requirements.txt`）；启动 `uvicorn server.main:app --reload --port 3001`；根 `package.json` 增加便捷脚本 `"dev:server": "uvicorn server.main:app --reload --port 3001"`，仅为统一命令入口，Python 依赖不进 npm。
- 阶段二预留：检索与微调依赖（sentence-transformers、milvus-lite 等）届时追加到 requirements.txt，不影响阶段一启动。
- **实施状态（2026-10-08）**：已建 `main.py`、`config.py`、`routers/{collate,health}.py`、
  `services/{llm,confidence,prompt_loader}.py`、`utils/{errors,schemas,rate_limit}.py`、`prompts/`、`tests/`。
  相对上面的结构图有三处差异：
  ① 新增 `services/prompt_loader.py`——Prompt 资产按 `## SECTION` 分段加载并渲染 `{{占位符}}`，
     故意不做缓存，改完 `.md` 立即生效（`.md` 改动不会触发 `uvicorn --reload`）；
  ② 新增 `requirements-dev.txt`（pytest），与生产依赖分开，避免测试依赖上线；
  ③ 新增 `server/tests/`，含一个**明确标记的本地假模型端点**（仅供离线联调与自动化测试，
     生产代码不引用），用于无真实密钥时验证整条代码路径与各降级分支。
  `routers/ocr.py`、`routers/translate.py`、`routers/export_note.py`、`services/ocr.py`、
  `services/note_template.py` **尚未创建**，分别对应 F7 / F6 / F4 的服务端部分。
- 解释器版本闸门：`server/__init__.py` 在 `sys.version_info < (3, 11)` 时直接抛出可读提示，
  避免误用低版本 Python 时报出难以定位的 pydantic TypeError。

## 5. Prompt 设计（核心资产，写进方案"核心技术模块"）

**校勘主 Prompt（system 角色设定）**："你是中国古典文献学校勘专家，熟悉讹字、衍文、脱文、通假字、异文五类校勘类型，依据形近、音近、义理、对文、版本五条校勘路径给出建议。"

**输出契约**（强制 JSON，few-shot 给 1 个《论语》示例）：
```json
{
  "items": [{
    "type": "讹字|衍文|脱文|通假|异文",
    "original": "原文片段",
    "suggested": "建议文本",
    "reason": "校勘理由（引用版本/义理，≤50字）",
    "confidence": 0.0,
    "offset": 12
  }],
  "translation": "白话译文"
}
```

**自校验清单放进 user prompt 尾部**：建议必须可在原文中定位；不确定时降低置信度而非硬改；通假只标注不替换（文献学惯例，这本身就是方案里的学科适配亮点）。

**`suggested` 必须与 `original` 不同（v2 收紧，实测驱动）**：v1 允许"原文无须改动时与 `original` 一致"，
结果真实模型对异文类就产出 `original = suggested = 「豫章故郡」`——把别本写法（「南昌故郡」）
只写进了理由。后果有三层：卡片显示成 `X → X` 的空操作；校勘记生成「一作「豫章故郡」」的自指句；
阶段二要给对校引擎输出的**异文清单**也无从结构化。因此 v2 规定：

| 类型 | `suggested` 填什么 |
|---|---|
| 讹字 / 衍文 / 脱文 | 校改后的片段 |
| 通假 | 本字 |
| 异文 | **别本异文写法**（不是底本写法） |

没有可提出的改动或别本写法时，**不要报这一条**（宁缺勿滥，与本 Prompt 一贯的"不确定就降置信度
而不是硬改"一致）。后端另在 schema 闸门兜底：`suggested == original` 的条目丢弃并计入
`droppedCount`（API.md §2）。

**置信度修正（services/confidence.py）**：命中通假字表/形近字表 +0.1；模型置信度 <0.7 的建议默认折叠到"低置信"分组，不进一键采纳。

## 6. 校勘记体例生成（F4，差异化卖点）

模板（按类型）：
- 讹字：「X」，底本误作「Y」，{理由}，今据改。
- 衍文：「X」下衍「Y」字，今删。
- 脱文：「X」下脱「Y」，{理由}，今补。
- 通假：「X」通「Y」，{释义}。
- 异文：「X」，一作「Y」，{取舍理由}。

其中 X 取 `original`、Y 取 `suggested`：讹字类的 X 是校正后写法、Y 是底本误字；
通假类的 X 是借字、Y 是本字；异文类的 X 是底本写法、Y 是**别本异文**。
由于两字段保证不同（见 §5），模板不会生成「一作 X」这种自指句。

前端按采纳的条目逐条生成；后端 exportNote 接口提供同逻辑服务端版本（**尚未实现**，见 §4 实施状态）（用于视频里演示"导出规范校勘记"）。

## 7. 效果验证实验设计（应用效果 20 分的弹药）

- **数据集**：选 10 段公共版权古籍（《论语》《孟子》《史记》选段），以权威整理本为 ground truth；每段 200–500 字，含天然 OCR 错误 + 人工注入错误（形近字替换、衍字、脱字，共 ≥60 个错误点）。
- **指标**：检出率 recall、误报率、校正准确率、F1；记录在 `docs/eval/`（实验脚本 + 原始结果 CSV）。
- **效率实验**：≥3 名参与者，同一段文本 A/B：纯手工校勘计时 vs 本系统辅助计时，算提升倍数与置信区间。
- **试点问卷**：≥20 名文科学生，前后两测（痛点认知 + 用后满意度），结果出图表。

## 8. 部署与演示保障

- 开发：前端 5173、后端 3001；演示当天 `npm run build` + 静态托管或本地 `vite preview`，后端本地常驻，备用热点防断网。
- 模型双供应商切换命令写进 README；演示前跑一遍 `/api/v1/health` 和一条真实校勘作为冒烟检查。
- 录屏预案：演示视频 3–5 分钟脚本顺序 = 痛点(20s) → 粘贴/OCR 上传(30s) → AI 校勘结果与采纳决策(60s) → 时间线留痕(20s) → 导出校勘记(20s) → 文白对照/划词释义(20s) → 实验数据与试点结论(30s)。

## 9. 安全与合规（写进方案"符合学科规范"）

- 用户文本服务端不落盘、不训练；API 密钥仅服务端。
- 古籍文本使用公共版权版本，引用权威整理本注明出处（参考文献进附录）。
- 所有交付物执行匿名自查清单（无学校/导师/姓名）。
