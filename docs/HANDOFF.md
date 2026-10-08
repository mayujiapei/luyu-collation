# 交接文档（HANDOFF）— 给执行会话

> 版本：v1.1（2026-10-08）。本文件是执行会话的第一入口：接手任何任务前先完整读完本文，再按 §3 顺序读契约文档。

## 1. 项目是什么、为了什么

- **项目**：古籍智能校勘系统——大模型驱动的"AI 建议 + 人工决策 + 全程留痕"人机协同校勘 Web 应用，输出符合文献学规范的校勘记。
- **目的**：参加 2026 第八届全球校园人工智能算法精英大赛·算法创新赛**赛题 5（AI+学科交叉）**，学科领域 = 中国古典文献学/汉语言文学。**目标是全国总决赛获奖**，不是完赛。
- **战略**：三阶段武装（入场券 → 四法引擎+证据 → 国赛冲刺），详见 `docs/ROADMAP.md`。当前处于**阶段一**。

## 2. 硬性红线（违反即任务失败，优先级最高）

1. **匿名红线**：一切参赛交付物（技术方案、视频脚本、PPT、佐证材料、README 截图）中严禁出现学校名称、Logo、指导教师、队员真实姓名。
2. **质量红线**：演示主链路（粘贴文本 → AI 校勘 → 采纳/还原 → 导出校勘记）不允许出现硬编码演示数据；mock 只允许存在于测试与开发降级路径，且必须有明显标记。大模型返回的 JSON 必须经 schema（pydantic）校验后才能进 UI，校验失败走降级提示，不得渲染脏数据。
3. **密钥红线**：API 密钥只放 `.env`，永不提交；`.env` 在 `.gitignore` 中。
4. **数据红线**：用户数据文件默认只读；修改写入带时间戳的新文件，不覆盖原文件；删除/覆盖前先读取目标确认。
5. **工具红线**：前端包管理只用 **npm**（锁定文件是 package-lock.json），禁 pnpm/yarn；Python 用 pip + `.venv`，Python 依赖不进 npm。

## 3. 文档阅读顺序（每次开工前）

1. `AGENTS.md`（根目录）——工作约定
2. `docs/ROADMAP.md` ——确认当前阶段与该阶段武器清单
3. `docs/PRD.md` ——功能范围与验收标准（阶段一 = F1–F8）
4. `docs/TECH_DESIGN.md` ——架构、选型、后端结构、Prompt 设计（已定稿 FastAPI）
5. `docs/API.md` ——前后端接口契约（框架无关，无需改动）

范围有变化时**先改文档再改代码**，代码与文档冲突以文档为准。

## 4. 仓库现状（截至 2026-10-08）

**已有（F1–F3 主链路已打通）**：
- 前端：Vue 3 + Vite，4 个路由页；opencc-js 繁简转换可用；TranslatorWidget（划词释义悬浮球）、GujiUpload、AnnotationTooltip 组件已有 UI。
- 数据层已接真实接口：`src/api/client.js`（统一 baseURL/超时/错误结构）、`src/stores/collation.js`（原文/建议/译文/决策/时间线）、`src/utils/collationNote.js`（校勘记体例，纯规则）。Pinia 已在 `main.js` 中启用。
- 后端：`server/`（FastAPI，端口 3001）已有 `POST /api/v1/collate` 与 `GET /api/v1/health`；模型输出过 pydantic 双闸门，`original` 非原文子串的条目丢弃并计入 `droppedCount`，契约外的脏数据不进 UI。
- Prompt 资产：`server/prompts/` 下 `collate_v1.md`、`translate_text_v1.md`、`explain_v1.md`；回归集 8 段在 `server/prompts/regression/`。
- 测试：后端 pytest 37 项（`server/tests/`）、前端 vitest 31 项（测试文件跟随源码放置）；
  另有 Prompt 回归集执行器 `server/tests/run_regression.py`（需真实密钥，会真实调用）。
- 工程配置：`.env.example`、`requirements.txt` + `requirements-dev.txt`；`.gitignore` 已忽略 `.venv/` 与 `__pycache__/`。

**仍未做**：
- `server/routers/ocr.py`、`server/routers/translate.py`、`server/routers/export_note.py`，以及 `server/services/ocr.py`、`server/services/note_template.py` 均未创建——分别属 F7 / F6 / F4 的服务端部分。
- 前端 `TranslatorWidget.vue` 仍是 `mockDict` 硬编码（F6）；`HistoryView.vue` 仍是硬编码演示记录（阶段一无持久化，且 TECH_DESIGN §3 明确本阶段不改该页；演示前按 §6 隐藏入口）。
- EVAL 标注规范、问卷模板仍未写（deadline 见 §6）；EVAL 还需给出「模型额外报出的合法校勘点」
  如何判定（否则会低估 precision，见 §7 观察 1）。

## 5. 已定决策（不要重新讨论、不要另立方案）

| 决策 | 定论 |
|---|---|
| 前端框架 | 不重构，Vue 3 + Vite 保持；只改数据来源（store + API） |
| 后端 | Python + FastAPI，端口固定 3001 |
| 大模型 | 通义千问主用，DeepSeek 备用，OpenAI 兼容接口，`LLM_PROVIDER` 环境变量切换 |
| OCR | 百度 OCR 高精度版（P1，10/05 接不上就砍，粘贴路径足够） |
| 规则 vs 模型 | 繁简转换、校勘记生成走规则不调模型；置信度经规则修正 |
| 校勘类型 | 五类固定：讹字、衍文、脱文、通假、异文 |
| 数据库 | 阶段一无持久化，无状态（阶段二才引入 SQLite） |

> 大模型接入现状（2026-10-08）：演示与联调实际走的是**小米 MiMo 开放平台**
> （`mimo-v2.6-pro`，API 端点 `https://api.xiaomimimo.com/v1`，见 §7）。
> 选型结论不变——仍是「OpenAI 兼容接口 + 环境变量切换」，且已用**两家**供应商
> （MiMo、硅基流动）验证过只需改 `LLM_PROVIDER`/`LLM_BASE_URL`/`LLM_MODEL` 三个环境变量、
> 代码零改动。但写技术方案时口径要与实际一致：可以说「抽象了 OpenAI 兼容层、可切换多供应商
> （MiMo 与硅基流动均实测）」，不要写成主用了没实际跑过的通义千问。

## 6. 阶段一实施顺序与两份未写文档

按依赖关系排序，不设日历日期：

1. **F1+F2+F3 端到端真实链路（粘贴路径）—— 已完成（2026-10-08）**，见 §7；
2. F4 校勘记导出 + F5 译文真实化 + 加载/错误态 —— **部分完成**：译文已随 `/collate` 由模型真实返回（F5 主体），
   加载/空态/错误态已随第 1 步补齐；校勘记目前由前端按文献学体例生成，
   **后端 `POST /export/collation-note` 端点与 `services/note_template.py` 仍未建**（属 F4 服务端部分）；
3. F6 划词释义 + F7 OCR（闸门：时间不够砍 F7）—— 未开始；
4. 对比实验 + 试点问卷 —— 未开始。

未写的两份文档不阻塞开发，但需在对应工作开跑前完成：
- **问卷模板**：招募试用同学有提前量，先于试点发放前定稿；
- **EVAL.md 标注规范**：对比实验开跑前必须定稿。

## 7. 第 1 步任务（阶段一 P0）：**已完成（2026-10-08）**

**任务**：打通"首页粘贴古籍文本 → 后端调大模型校勘 → 校勘页渲染真实建议 → 采纳/还原 → 导出校勘记"的端到端真实链路。

具体拆解：
1. 建 `server/`（FastAPI 骨架 + `POST /api/v1/collate` + `GET /api/v1/health`），pydantic 校验模型输出，`original` 必须是原文子串（不满足丢弃并计入 `droppedCount`）。
2. 新建 `src/stores/collation.js` + `src/api/client.js`，HomeView"开始校勘"真实调 `POST /collate`，结果写 store 后跳转。
3. CollationView 改为从 store 渲染，删除全部硬编码数据；补 loading / 空态 / API 错误态；校勘卡片加类型徽标。
4. 三个 Prompt 定稿入 `server/prompts/`（collate / translate_text / explain），回归集 5–10 段固定文本入 `server/prompts/regression/`。

**验收标准（全部满足才算完成）**：
- `npm run build` 通过；`uvicorn` 启动无报错；`/api/v1/health` 返回 ok。
- 手动走通：粘贴一段真实古籍文本（非《论语》演示例）→ 校勘页出现模型返回的真实建议 → 逐条采纳/还原 → 时间线更新 → 导出校勘记文件内容正确。
- 断网或密钥缺失时前端有明确降级提示，不白屏、不渲染脏数据。
- 主链路代码里搜不到演示用硬编码数据。

**核对结果**：`npm run build` 通过、`uvicorn` 启动无报错、`/api/v1/health` 返回 ok；
用《左传·曹刿论战》选段（非《论语》演示例，含人工注入的形近误字）走通全链路，导出得到符合体例的校勘记；
断网时首页与校勘页均有明确提示（含错误码与处理建议），未白屏、未渲染脏数据；主链路已无硬编码演示数据。
**说明**：上述核对最初是用本地假模型端点（`server/tests/fake_llm_provider.py`）验证的；
真实模型已于 2026-10-08 接通并通过回归集，见下。

### 遗留验证（真实模型）：**已完成（2026-10-08）**

**供应商**：小米 MiMo 开放平台（控制台 `https://platform.xiaomimimo.com`）。
注意区分：**实际 API 端点是 `https://api.xiaomimimo.com/v1`**，
`platform.*` 那个域名是控制台 SPA（任何路径都回 200，容易误当成接口）；两者极易搞混。
接入仍然只改环境变量、**代码零改动**——这是第二次验证「供应商可插拔」（TECH_DESIGN §2）：

```
LLM_PROVIDER=xiaomi-mimo
LLM_BASE_URL=https://api.xiaomimimo.com/v1
LLM_MODEL=mimo-v2.6-pro
```

平台可用文本模型：`mimo-v2.6-pro` / `mimo-v2.6-flash` / `mimo-v2.5-pro` / `mimo-v2.5`
（另有 asr / tts 系列，非本用途）。本项目选 `mimo-v2.6-pro`。

**回归集 8/8 通过**（`./.venv/Scripts/python.exe -m server.tests.run_regression`）：

| 用例 | 类别 | 结果 |
|---|---|---|
| reg-001～004 | 干净对照 ×4 | 均 **0 条建议**，零误报 |
| reg-005 | 讹字 | 「代→伐」检出，理由引形近 + 通行本 |
| reg-006 | 脱文 | 「其名鲲→其名为鲲」检出，理由引**对文**（与下文「其名为鹏」相对） |
| reg-007 | 衍文 | 「舍舍去→舍去」检出，理由引版本与文义 |
| reg-008 | 通假 | 「蚤→早」检出，理由明确写「只标注不替换」（文献学分寸守住） |

8 例 `droppedCount` 全为 0：模型输出每次都满足 JSON 契约，未经任何丢弃。
单次调用 3.7～19.3 秒（最长 19.3s），在 PRD §5 的 30s 预算内。
浏览器端也复跑了完整主链路（真实模型 → 建议渲染 → 采纳 → 导出校勘记，内容正确）。

**两条要留意的观察**：

1. **模型会主动补报注入错误之外的合法校勘点。** reg-006 除注入了脱文外，它还报了
   「「冥」通「溟」（大海之义）」——这是《庄子》「北冥」的经典训释，属真学问而非幻觉，
   且正确判为通假、只标注不替换。但做评测集时要意识到：这类"额外正确"条目若按误报计，
   会低估 precision。**`docs/EVAL.md` 必须给出这类条目的判定口径**（建议单列一档
   「正确但非注入项」）。
2. **导出体例有一处轻微重复。** 若模型理由里已写「据《左传》通行本作…」，模板再追加
   「今据通行本改」会读起来重复。当前是按 TECH_DESIGN §6 的体例实现（理由与「今据改」
   同时出现），是否精简留到 F4 决定。

**若换回硅基流动**：其账号余额曾耗尽，所有调用返回 `HTTP 402 ... balance is insufficient`
（前端表现为 `PROVIDER_MISCONFIGURED` 并带上游状态码，属预期行为）。该供应商配置在
`.env` 里注释保留，充值后取消注释即可。

## 8. 环境备忘

- Node ^22.18.0 / >=24.12.0；Python >= 3.11。
- 首次搭建：`py -3.11 -m venv .venv` → `.venv/Scripts/pip install -r requirements.txt`
  （要跑测试再加 `-r requirements-dev.txt`，含 pytest）。
- **启动后端前必须激活 `.venv`**：`npm run dev:server` 依赖 PATH 上的 `uvicorn`。
  若误用系统自带低版本 Python，`server/__init__.py` 的版本闸门会拦下并打印正确的启动方式
  （否则报错会是一句难以定位的 pydantic TypeError）。
- 常用命令：`npm run dev`（前端 5173）、`npm run dev:server`（后端 3001）、
  `npm test`（前端 vitest）、`.venv/Scripts/python -m pytest server/tests`（后端 pytest）。
- 需要的密钥（放 `.env`，参照 `.env.example` 与 TECH_DESIGN §4）：`LLM_API_KEY` 必需；
  `OCR_API_KEY`/`OCR_SECRET_KEY` 在做 F7 时才需要。
  填好后**无需重启后端**即生效（配置按请求重读 .env；真实环境变量优先级高于 .env）。
  密钥只在服务端使用，前端产物中不含其值——已用探针密钥实测确认。
- 前端 5173、后端 3001；跨域由 FastAPI CORS 处理（已允许 5173 与 4173 的本机来源）。
- **无真实密钥时的离线联调**：见 `server/tests/README.md`（启动假模型端点、指定环境变量、
  预期返回值与各故障分支的完整步骤）。
