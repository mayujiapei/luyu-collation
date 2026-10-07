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
| `LLM_TIMEOUT` | 504 | 大模型超时（>30s） |
| `LLM_BAD_JSON` | 502 | 模型输出未通过 JSON schema 校验（前端提示重试） |
| `RATE_LIMITED` | 429 | 触发限流 |
| `PROVIDER_MISCONFIGURED` | 500 | 密钥缺失 |

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
`options` 可省略，默认如上。

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
- `offset` 为 `original` 在 `text` 中的首字符下标

**Response 200 扩展字段**：`"droppedCount": 0`（模型输出被规则过滤的条数，用于方案里"输出可靠性控制"的佐证）。

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
