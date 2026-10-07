# 古籍智能校勘系统 — 工作约定

## 安全红线（最高优先级）
- 用户数据文件默认只读；任何修改写入带时间戳的新文件，不覆盖原文件。
- 删除或覆盖前，先读取目标内容确认。
- 参赛交付物（技术方案、演示视频脚本、PPT、佐证材料、README 截图）中**严禁出现学校名称、Logo、指导教师、队员真实姓名**——这是赛规公平性红线，违反直接取消资格。
- API 密钥只放 `.env`，永不提交；`.env` 已在 `.gitignore` 中，新增密钥文件先确认被忽略。

## 工作流
- 非平凡任务先调查、提问、提计划，批准后再动手。
- 实现完成后走检查-修复循环（`npm run build` 通过 + 手动走通主流程），无必须修复项才算完成。
- 需求/范围有变化时，先改 `docs/` 里的文档，再改代码；代码与文档冲突以文档为准。

## 技术栈
- 前端：Vue 3 + Vite + Pinia + vue-router + opencc-js；构建 `npm run build`；开发 `npm run dev`。
- 后端：Python + FastAPI（`server/` 目录），开发 `npm run dev:server`（等价 `uvicorn server.main:app --reload --port 3001`）；Python 依赖用 `requirements.txt` + `.venv`，不进 npm。
- 包管理器：前端用 npm（不要用 pnpm 或 yarn，仓库锁定文件是 package-lock.json）；Python 用 pip。
- 运行时版本：Node ^22.18.0 或 >=24.12.0；Python >= 3.11。

## 子代理路由
- 探索、检索、核验一律派 Explore（只读）；不要用 general-purpose 做只读任务。
- 写操作或全工具并行委派才用 general-purpose。
- 奠基性文档（`docs/` 下架构、需求、接口）直接读，不外包。

## 文档事实来源
- `docs/ROADMAP.md`：三阶段战略统领；动手前先读它确认当前处于哪个阶段。
- `docs/PRD.md`：需求与范围的唯一事实来源。
- `docs/TECH_DESIGN.md`：架构、技术选型、Prompt 设计的唯一事实来源。
- `docs/API.md`：前后端接口契约的唯一事实来源；改接口先改它。

## 质量红线
- 演示主链路（粘贴文本 → AI 校勘 → 采纳/还原 → 导出校勘记）不允许出现硬编码演示数据；mock 只允许存在于测试与开发降级路径，且必须有明显标记。
- 大模型返回的 JSON 必须经 schema 校验后才能进 UI，校验失败走降级提示，不得渲染脏数据。
