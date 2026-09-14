# contracts/ —— API 契约中立场

本目录存放 EDP 数据平台的对外 API 契约快照。W1 冻结基线 = `openapi.json` + `openapi.sha256`（随 EDP-007 交付生成）。

## 变更流程（冻结后三联动）

契约一经冻结（M1 出口条件），任何变更必须同时完成以下三步，缺一不可：

1. **PR**：标题前缀 `[contract]`，正文附变更动机、影响面与向后兼容性说明；
2. **Tech Lead 评审**：评审人必须包含 Tech Lead，未经评审合入视为流程违例；
3. **SDK 重生成**：执行前端 SDK 生成管线重新生成产物与指纹，PR 内必须包含 `openapi.json` / `openapi.sha256` / SDK 生成目录三者一致变更，并记录对应 SDK 重生成 commit hash。

## 快照与指纹说明（框架）

- `openapi.json`：由 `backend/scripts/export_openapi.py` 从 FastAPI app 导出的排序稳定 JSON；
- `openapi.sha256`：对 `openapi.json` 文件字节的 SHA-256 指纹；
- CI 双门禁：后端「导出 diff 门禁」+ 前端「SDK 指纹比对门禁」，任一不一致即 PR 失败。

> 校验命令、变更评审模板等详细内容随 EDP-007（契约冻结基线）任务补充。
