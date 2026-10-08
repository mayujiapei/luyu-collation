# 交接文档（HANDOFF）— 给执行会话

> 版本：v1.0（2026-10-03）。本文件是执行会话的第一入口：接手任何任务前先完整读完本文，再按 §3 顺序读契约文档。

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

## 4. 仓库现状（截至 2026-10-03）

**已有**：
- Vue 3 + Vite 前端（`src/`），4 个路由页：HomeView（上传/粘贴入口）、CollationView（双栏校勘台，核心 UI 已成型）、HistoryView、AboutView。
- opencc-js 繁简转换已可用（`src/utils/converter.js`）；TranslatorWidget（划词释义悬浮球）、GujiUpload、AnnotationTooltip 组件已有 UI。
- Pinia 已安装**但未被使用**（`src/stores/counter.js` 是脚手架残留）。

**没有（= 阶段一要建的）**：
- `server/` 目录整个不存在——FastAPI 后端从零建，结构照 TECH_DESIGN §4。
- `.env` / `.env.example`、`requirements.txt`、任何真实 API 调用。
- **前端所有数据全是硬编码 mock**：`CollationView.vue` 内的 `originalData`、`collationItems`、`translationText`，`TranslatorWidget.vue` 内的 `mockDict`，HomeView 的"开始校勘"只 console.log 后直接跳转。这些是阶段一 P0 要消灭的目标。
- Prompt 资产（`server/prompts/`）、回归集、EVAL 标注规范、问卷模板（后两份 deadline 见 §6）。

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

## 6. 阶段一实施顺序与两份未写文档

按依赖关系排序，不设日历日期：

1. F1+F2+F3 端到端真实链路（粘贴路径）——**当前任务**；
2. F4 校勘记导出 + F5 译文真实化 + 加载/错误态；
3. F6 划词释义 + F7 OCR（闸门：时间不够砍 F7）；
4. 对比实验 + 试点问卷。

未写的两份文档不阻塞开发，但需在对应工作开跑前完成：
- **问卷模板**：招募试用同学有提前量，先于试点发放前定稿；
- **EVAL.md 标注规范**：对比实验开跑前必须定稿。

## 7. 第一个任务（阶段一 P0）与验收标准

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

## 8. 环境备忘

- Node ^22.18.0 / >=24.12.0；Python >= 3.11（`python -m venv .venv`，依赖装 `requirements.txt`：fastapi、uvicorn、pydantic、httpx）。
- 需要的密钥（放 `.env`，参照 TECH_DESIGN §4 环境变量清单）：`LLM_API_KEY` 必需；`OCR_API_KEY`/`OCR_SECRET_KEY` 在做 F7 时才需要。
- 前端 5173、后端 3001；跨域由 FastAPI CORS 处理。
