# 接口文档 — 古籍智能校勘系统（前后端契约）

> 版本：v1.0（2026-10-02）。改接口先改本文档，前后端以此为准。
> Base URL：开发 `http://localhost:3001`；前缀 `/api/v1`。
> 统一错误格式：`{ "error": { "code": "...", "message": "..." } }`，HTTP 状态码语义化。

## 错误码一览

| code | HTTP | 含义 |
|---|---|---|
| `TEXT_TOO_LONG` | 413 | 文本超过 5000 字 |
| `INVALID_REQUEST` | 400 | 参数/schema 校验失败 |
| `OCR_FAILED` | 502 | OCR 服务失败 |
| `LLM_TIMEOUT` | 504 | 大模型超时（单次调用硬性总时限 60s） |
| `LLM_BAD_JSON` | 502 | 模型输出未通过 JSON schema 校验（前端提示重试） |
| `RATE_LIMITED` | 429 | 触发限流 |
| `PROVIDER_MISCONFIGURED` | 500 | 模型通道不可用：密钥缺失、密钥无效，或上游返回 4xx/5xx、连不上 |
| `INTERNAL_ERROR` | 500 | 服务端内部错误（未预期异常、Prompt 资产缺失等），详情见后端日志 |

**上游失败的归口说明**：`PROVIDER_MISCONFIGURED` 不限于「密钥缺失」，也承接「上游服务不可用」
（网络不通、上游 4xx/5xx、配额受限）。带上游状态码与响应摘要写在 `message` 里便于现场定位；
前端对这三类一视同仁——给出明确降级提示，不渲染脏数据。超时仍单独用 `LLM_TIMEOUT`。

---

## 1. POST /ocr — 古籍图片识别（F7，P1）

**Request**：`multipart/form-data`，字段 `image`（jpg/png，≤10MB）。

**Response 200**：
```json
{
  "text": "识别出的全文文本",
  "provider": "baidu",
  "elapsedMs": 1230
}
```

失败返回 `OCR_FAILED`；前端降级提示"识别失败，请改用粘贴文本"。

---

## 2. POST /collate — 智能校勘（核心，F2/F5）

**Request**：
```json
{
  "text": "待校勘古籍文本（≤5000字）",
  "options": {
    "checkTypes": ["讹字", "衍文", "脱文", "通假", "异文"],
    "produceTranslation": true,
    "referenceEdition": "通行本"
  }
}
```
`options` 可省略，默认如上；显式传 `null` 视同省略。

**Response 200**：
```json
{
  "requestId": "req_20261002_ab12cd",
  "model": "qwen-max",
  "elapsedMs": 5210,
  "items": [
    {
      "id": 1,
      "type": "讹字",
      "original": "日",
      "suggested": "曰",
      "reason": "形近而讹，据《论语》通行本当作「曰」",
      "confidence": 0.95,
      "offset": 3
    }
  ],
  "translation": "白话译文（produceTranslation=false 时为空字符串）"
}
```

**字段约束（前后端共同遵守）**：
- `type` ∈ {`讹字`, `衍文`, `脱文`, `通假`, `异文`}
- `confidence` ∈ [0,1]；<0.7 的条目前端折叠为"低置信建议"，不参与"全部采纳"
- `original` 必须是 `text` 的子串（后端校验，不满足则丢弃该条并计数返回 `droppedCount`）
- `suggested` **必须与 `original` 不同**，且承载该类型的具体内容：讹字 / 衍文 / 脱文填校改后的片段，
  通假填本字，**异文填别本异文写法**（不是底本写法）。没有可提出的改动或别本写法时，不要报这一条
- `offset` 为 `original` 在 `text` 中的首字符下标
- `id` 由后端按序分配（模型输出契约中无此字段，见 TECH_DESIGN §5），前端不自行生成

**Response 200 扩展字段**：`"droppedCount": 0`（模型输出被规则过滤的条数，用于方案里"输出可靠性控制"的佐证）。
计入 `droppedCount` 的四种情况：① 单条不合 schema（类型不在五类内、缺理由、置信度越界等）；
② `original` 不是 `text` 的子串；③ `suggested` 与 `original` 相同（空操作，见上）；
④ 与已有条目完全重复（同类型、同原文、同建议）。
逐条丢弃而非整批报错——一条坏数据不该废掉整次校勘。
即使全部条目都被丢弃，仍返回 200（`items` 为空数组、`droppedCount` 为丢弃总数），
由前端说明「未发现问题 / 有 N 条建议被拦截」；只有**信封级**失败（内容不是 JSON、
`items` 不是数组）才回 `LLM_BAD_JSON`。
`offset` 一律由后端按 `text.find(original)` 重新定位，不采信模型自报值；
返回的 `items` 按 `offset` 升序排列。

---

## 3. POST /translate — 划词释义（F6）

**Request**：
```json
{ "text": "不亦说乎", "context": "前后各 50 字的上下文，可为空字符串" }
```

**Response 200**：
```json
{ "explanation": "「说」通「悦」，愉快、高兴。", "elapsedMs": 1500 }
```
`text` ≤100 字，超出返回 `INVALID_REQUEST`。

---

## 4. POST /export/collation-note — 生成规范校勘记（F4）

**Request**：
```json
{
  "sourceText": "原始文本",
  "acceptedItems": [
    { "type": "讹字", "original": "日", "suggested": "曰", "reason": "形近而讹，据通行本改" }
  ],
  "title": "可选，篇章名"
}
```

**Response 200**：
```json
{
  "noteText": "校勘记\n一、「曰」，底本误作「日」，形近而讹，今据通行本改。\n",
  "format": "txt",
  "elapsedMs": 120
}
```
纯规则模板生成，不调用大模型，保证离线可用（演示兜底）。

---

## 5. GET /health — 冒烟检查

**Response 200**：
```json
{ "status": "ok", "llmProvider": "qwen", "ocrConfigured": true }
```
演示前必跑；`ocrConfigured=false` 时前端隐藏 OCR 入口走粘贴路径。

---

## 前端调用映射（防止实现时走样）

| 页面动作 | 调用 |
|---|---|
| HomeView 粘贴文本 → 开始校勘 | POST /collate → 结果写 Pinia → 跳 /collation |
| HomeView 上传 .txt | 前端读文件内容 → 同粘贴路径 |
| HomeView 上传图片 | POST /ocr → text 写 Pinia → POST /collate |
| CollationView 全部采纳/一键还原 | 纯前端状态操作，不调接口（confidence<0.7 除外规则见 §2） |
| 导出校勘记 | POST /export/collation-note（失败时前端本地模板兜底生成） |
| 划词释义 | POST /translate |
