# scene_agent · Scene Agent PoC（#165 第一期形态）

独立 Python HTTP 服务 + 最小线性整数版本链 + SHA256 文件回读 + undo/rollback。
**不依赖 UE5、GPU、网络或第三方库**；只用标准库，默认绑定 `127.0.0.1`。

对应学长 11-16 拍板的 D6（独立服务 + `v0000` 基线 + 单写者乐观锁 + `manifest_sha256` 回读 + undo/rollback），
以及 Issue #1 的 10 个 `scene_*` 接口草案。

## 快速开始

```powershell
python -m scene_agent.server --root ./scene_agent_data --port 8765
```

另开终端导入示例场景（项目根目录）：

```powershell
curl.exe -s -X POST http://127.0.0.1:8765/v1/scene/import `
  -H "Content-Type: application/json" `
  --data-binary "@dji_ue5_3dgs/scene_agent/examples/scene_import_demo.json"
```

示例已带一次性 `run_id` / `command_id`，可直接导入。然后 dry-run 一条自然语言指令：

```powershell
curl.exe -s -X POST http://127.0.0.1:8765/v1/scene/edit/plan `
  -H "Content-Type: application/json" `
  -d '{\"scene_id\":\"campus_demo\",\"utterance\":\"把3号楼往东移5米\"}'
```

返回的 `intent_id` + `intent.scene_ref` 用于提交（`confirm=true` 必填）：

```powershell
curl.exe -s -X POST http://127.0.0.1:8765/v1/scene/edit/commit `
  -H "Content-Type: application/json" `
  -d '{\"scene_ref\":{\"scene_id\":\"campus_demo\",\"scene_version\":0,\"manifest_sha256\":\"<load 返回值>\"},\"intent_id\":\"<plan 返回值>\",\"expected_version\":0,\"confirm\":true,\"run_id\":\"r2\",\"command_id\":\"c2\"}'
```

## 接口（12 个路由，其中 10 个来自 Issue #1）

| 路由 | 风险 | confirm | 说明 |
|---|---|---|---|
| `POST /v1/scene/import` | write | false | 一次性导入，创建 `v0000`（额外路由，Issue #1 §2.1.5） |
| `POST /v1/scene/load` | read | false | 加载当前/指定版本 |
| `POST /v1/scene/query` | read | false | 列元素（名称/类/tag/bbox/分页） |
| `POST /v1/scene/get` | read | false | 单元素 + derived |
| `POST /v1/scene/edit/plan` | read | false | 自然语言或结构化 ops → intent + diff 预览，不写盘 |
| `POST /v1/scene/edit/commit` | write | **true** | 提交新版本（expected_version 乐观锁） |
| `POST /v1/scene/verify` | read | false | L1–L4 回读 |
| `POST /v1/scene/versions` | read | false | 版本列表 + 链完整性 + orphan |
| `POST /v1/scene/rollback` | write | **true** | 回滚 = 基于旧版本新建版本 |
| `POST /v1/scene/undo` | write | **true** | 重放当前 diff 的 inverse_ops |
| `POST /v1/scene/checkpoint/save` | write | false | 存检查点 |
| `POST /v1/scene/checkpoint/open` | write | **true** | 从检查点新建版本 |

业务失败统一 **HTTP 200** + `{"ok":false,"error":{"code":"E_SCENE_*","message":...}}`；
协议错误 400/404/500。写操作必须带 `run_id`（缺 → `E_SCENE_RUN_ID_REQUIRED`）。

## 设计要点

- **整数线性链**：`v0000` 导入，之后每次 commit +1，永不复用；回滚/undo/checkpoint open 都生成新版本。
- **`scene.json` 只存对象图**（不含 version/parent），因此回滚后的 `scene_json_sha256` 能与目标版本逐字节相等；版本号记录在 `manifest.json` 与 `diff_from_parent.json`。
  > 这与 Issue #1 草案里把 `version` 放进 `scene.json` 的字段位置不同，语义不变，是为了让「回滚后 hash 相等」可验证。
- **规范化 JSON**：`sort_keys=True, separators=(",",":")` + 末尾换行；所有 hash 都基于这个形式。
- **原子提交**：先写 `vNNNN/` 并 fsync，L1–L4 回读通过后才 `os.replace` manifest；失败时 manifest 不变，新目录留在磁盘上，`versions` 会把它标成 orphan。
- **单写者**：`expected_version` 不匹配 → `E_SCENE_VERSION_CONFLICT`，不自动合并；intent 还绑定 plan 时的 scene hash，防止「确认的是 v7、执行时已是 v8」。
- **许可证门控**：`license.type/holder/evidence_path` 任一为 `待确认` 或缺失 → `license_status=draft`，可读可 plan，**不可 commit**（`E_SCENE_LICENSE_UNDECLARED`）。
- **splat 只读**：`geometry.kind in {splat, splat_ref}` 的元素拒绝 translate/rotate/scale（`E_SCENE_ASSET_NOT_EDITABLE`），只能改名/属性/删除。
- **幂等**：写操作带 `command_id` 时缓存最近 100 条结果，重复提交不会移动两次。
- **审计**：写操作追加 `audit/scene_audit_<run_id>.jsonl`，含单调 `seq`。

## 已知边界（PoC）

1. 没有 UE5 联动：`scene.json` 只是对象图，加载到编辑器是下一步。
2. intent 存在内存里，服务重启后过期；TTL 300 s。
3. 资产只登记 `assets_inventory.json`，没有上传/替换接口；`replace_asset` 的逆操作不在本期。
4. 自然语言解析器只支持「把 X 往东/南/西/北/上/下移 N 米」和「把 X 旋转 N 度」；真实 LLM 路径应该直接产出 `ops`。
5. 不支持分支/合并；单用户、无鉴权、只绑回环。
6. `E_SCENE_RUN_ID_REQUIRED`、`E_SCENE_ALREADY_EXISTS` 是 PoC 补充码，Issue #1 表里没有。

## 测试

```powershell
python -m unittest discover -s dji_ue5_3dgs/scene_agent/tests -v
```

覆盖：导入/加载、plan/commit、回读 L1–L4、冲突、confirm、许可证、splat 只读、锁定、no-op、
rollback/undo 的 hash 相等、checkpoint、幂等、版本链 orphan、HTTP 流程。
