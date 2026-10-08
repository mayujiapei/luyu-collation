# Prompt 回归集（regression）

> 用途：Prompt 改版（`collate_v1` → `collate_v2`）后，用同一组固定文本对比新旧版本的
> 检出与误报，作为「Prompt 也是可评测资产」的依据（TECH_DESIGN §4、§5）。
> 与评测基准的分工：**本目录只看 Prompt 是否退化，不是论文级的基准数据集**；
> 带标注规范的评测集在 `docs/EVAL.md` 定稿后单独构建（TECH_DESIGN §7）。

## 文件

| 文件 | 内容 |
|---|---|
| `collation_cases_v1.json` | 8 段固定文本 + 期望要点：4 段干净对照（看误报）、4 段人工注入错误（看检出） |

## 用例字段

- `kind: control` —— 干净通行本选段。理想结果 0 条建议；`maxItems` 是容忍上限，
  超出即视为 Prompt 误报退化。
- `kind: injected` —— 我方人工注入的错误，`expected.injected` 记录注入内容（ground truth），
  `expected.mustFind` 给出必须命中的要点：`originalContains` / `suggestedContains` 做子串匹配，
  刻意不用精确相等，避免因模型取片段长短不同而误判为未命中。
- `minItems` / `maxItems` —— 建议条数的可接受区间。

## 怎么跑

**推荐：用执行器一次跑完**（读 `.env` 里的真实密钥，产生真实调用费用）：

```bash
./.venv/Scripts/python.exe -m server.tests.run_regression             # 全部 8 条
./.venv/Scripts/python.exe -m server.tests.run_regression --verbose    # 附带每条建议内容
./.venv/Scripts/python.exe -m server.tests.run_regression --only reg-005
```

它逐条核对 `mustFind` / `minItems` / `maxItems` / 类型合法性，打印实际输出与耗时；
全部通过时退出码 0，可直接挂进演示前的冒烟流程。

**手动核对**：

1. 起后端（`npm run dev:server`），确认 `/api/v1/health` 返回 `status: ok`、`LLM_API_KEY` 已配置。
2. 逐条把 `source` 原文粘进首页「粘贴原文」，或直接调接口：

   ```bash
   curl -s http://localhost:3001/api/v1/collate \
     -H "Content-Type: application/json" \
     -d '{"text":"北冥有鱼，其名鲲。鲲之大，不知其几千里也。","options":{"produceTranslation":false}}'
   ```

3. 逐条比对：`items` 是否覆盖 `mustFind`、条数是否落在 `[minItems, maxItems]`。
4. 记录结果时**连同 `droppedCount` 一起记**：它反映有多少条模型输出没通过契约校验或被
   原文定位淘汰，是「输出可靠性控制」的佐证材料（API.md §2）。

## 注意

- **上游报错先看错误消息里的状态码**：本项目会把上游非 2xx 归口成 `PROVIDER_MISCONFIGURED`，
  并在 `message` 里带上游状态码与响应摘要。若看到 `HTTP 402 ... balance is insufficient`，
  那是模型账号余额不足（不是密钥错、也不是代码问题），充值后重跑即可。
- 用例文本为公共版权古籍通行本短选段，只作 Prompt 输入，不作校勘底本，不参与任何对外的
  准确率宣称；对外的指标一律以 `docs/EVAL.md` 定义的评测集为准。
- 用例使用简体输入。系统对繁体输入同样适用（前端默认以繁体展示），但本回归集暂不含繁体用例。
- 改用例要连同 `_v1` 一起另存新版本文件，留旧版本以便对比。
