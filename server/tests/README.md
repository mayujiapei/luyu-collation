# 后端离线联调与测试

> 本目录只放**不参与生产链路**的工具。`fake_llm_provider.py` 是允许存在的
> 「测试/开发降级路径」（AGENTS.md 质量红线），因此带明显标记，且不被任何生产代码导入。

## 为什么要有假模型端点

真实模型不可用时（没密钥、断网、不想消耗额度），仍然需要验证**真实代码路径**：

```
HTTP 请求 → 限流 → 入参校验 → Prompt 组装 → 上游调用 → JSON 提取
         → schema 校验 → 原文定位/去重丢弃 → 置信度规则修正 → 响应
```

假模型只替换最右端的「上游 HTTP 响应」，其余全是生产代码。这样验证到的结论对真实模型同样成立
（真实模型额外带来的是**内容质量**差异，那属于 Prompt 回归与评测集的范畴）。

## 用法

开两个终端。

**终端 1：假模型**

```bash
./.venv/Scripts/python.exe -m server.tests.fake_llm_provider --port 3010
```

**终端 2：后端（只在本地联调时这样设，别写进 .env）**

```bash
LLM_PROVIDER=qwen LLM_API_KEY=fake-key \
LLM_BASE_URL=http://127.0.0.1:3010/v1 LLM_MODEL=fake \
  ./.venv/Scripts/uvicorn.exe server.main:app --port 3001
```

**终端 3：校验**

```bash
curl -s http://localhost:3001/api/v1/collate -H "Content-Type: application/json" \
  -d '{"text":"齐师代我。公将战，不亦说乎。肉食者鄙，末能远谋。","options":{"produceTranslation":true}}'
```

期望（与 `FIXTURE_EXPECTED` 一致）：

- `items` 4 条，`id` 依次 1、2、3、4，`offset` 依次 2、11、14、19（按原文位置升序，由后端重新定位，不采信模型自报值）
- `confidence` 依次为 `1.0`、`1.0`、`0.55`、`0.98`：前两条由字表命中 +0.1 封顶到 1.0；
  第四条先生成 88 → 归一 0.88，再命中形近表（未/末）提到 0.98；
  第三条（异文）未命中任何字表，保持 0.55，前端会折叠进「低置信建议」且不参与「全部采纳」
- `droppedCount` = 3：类型不合法 1 条、原文定位失败 1 条、重复 1 条

换用 `server/prompts/regression/collation_cases_v1.json` 里 `reg-005` 的真实选段
（《左传》曹刿论战，含人工注入的「代」误字）时，期望 `items` 2 条
（讹字「代」、低置信异文「肉食者鄙」）、`droppedCount` = 5。

## 故障分支

改 `LLM_MODEL` 即可让假模型模拟各类上游故障，验证降级提示：

| `LLM_MODEL` | 假模型行为 | 期望前端/接口表现 |
|---|---|---|
| `fake` | 正常返回固定样本 | 200，见上 |
| `fake-badjson` | 返回非 JSON 散文 | `LLM_BAD_JSON` / 502，前端提示重试 |
| `fake-schemafail` | JSON 合法但信封结构不对 | `LLM_BAD_JSON` / 502 |
| `fake-timeout` | 挂起 120 秒 | `LLM_TIMEOUT` / 504 |
| `fake-error500` | 上游返回 500 | `PROVIDER_MISCONFIGURED` / 500，消息含上游状态码 |

另外两条不依赖假模型：

- **缺密钥**：不设 `LLM_API_KEY` 直接起后端，`/collate` 应返回 `PROVIDER_MISCONFIGURED`，
  消息提示去 `.env` 填写；`/health` 仍应返回 `status: ok`
- **断网**：把 `LLM_BASE_URL` 指向一个不可达地址，应返回 `PROVIDER_MISCONFIGURED`，
  前端出现明确降级提示而不是白屏
