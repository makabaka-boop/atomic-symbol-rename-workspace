# mini-lang 代码工作区

React + Monaco 前端、FastAPI + SQLite 后端的迷你代码工作区，演示一种只有
`def` 声明、`use` 引用和行尾注释（`#` 到行尾）的小语言。

- 工作区最多 **20 个文档**（前后端同时限制）。
- 符号名为 ASCII（`[A-Za-z_][A-Za-z0-9_]*`），注释可含任意 Unicode。
- 协议中所有位置为 **0 起始行号 + UTF-16 代码单元列**（与 Monaco/LSP 一致，
  前端转成 Monaco 的 1 起始）；emoji 等 astral 字符按 2 个 UTF-16 单元计。
- 诊断绑定**文档修订**：异步计算出的旧诊断不会覆盖新文本（服务端发送前
  再校验一次，客户端只在修订一致且无本地未提交修改时应用）。
- **跨文件重命名**两阶段：先预览（计划含全部修改范围、各文档基准修订、
  索引版本），确认后在 **SQLite 一次事务**中提交；任一相关文档已变化、
  出现同名声明、或索引已失效，都整批拒绝——不改到一半。
- 多个浏览器会话通过 WebSocket 收到**工作区修订通知**；本地未提交文字
  始终保留并显示冲突横幅，可查看服务器版本、加载服务器版本或强制保存。

## 目录

```
backend/
  app/lang.py        # 解析器：def/use/注释，UTF-16 列换算，范围替换
  app/db.py          # SQLite：文档/工作区修订，transaction() 全有或全无
  app/diagnostics.py # 诊断计算 + 异步分发（filter_fresh 丢弃过期结果）
  app/rename.py      # 重命名预览计划 + 单事务应用
  app/main.py        # FastAPI 路由与 WebSocket
  tests/             # pytest 测试（28 个）
frontend/
  src/workspace.ts   # 客户端控制器：修订跟踪、冲突、诊断防旧、重命名
  src/components/    # TabBar / EditorPane / ConflictBanner / RenameDialog
```

## 运行

```bash
# 后端（:memory: SQLite；传文件路径可持久化，见 create_app）
cd backend && pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000

# 前端（Vite 代理 /api 与 /ws 到 8000）
cd frontend && npm install && npm run dev
```

打开两个浏览器窗口即两个会话：一边保存，另一边无本地修改时自动跟随；
有本地未提交修改时显示冲突横幅。

## 测试

```bash
cd backend && python -m pytest tests/ -q
```

覆盖需求要点：

- `test_lang.py` / `test_diagnostics.py`：中文与 emoji 注释之后（及同行）
  的 UTF-16 定位；注释内容不被解析为代码；`apply_ranges` 不触碰注释。
- `test_rename.py`：预览计划含范围/基准修订/索引版本；预览期间并发编辑
  → `DOC_CHANGED` 且全批不变；预览后出现同名声明 → `NAME_CONFLICT`；
  无关文档变化 → `INDEX_STALE`；注释中的同名文本不被替换；20 文档上限。
- `test_ws.py`：两个会话同时收到 `workspace_revision`；连续提交时诊断
  只绑定最新修订（旧诊断不覆盖新文本）；重命名应用广播到所有会话。

## API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/documents` | 文档列表 + 工作区修订 |
| POST | `/api/documents` | 新建（超过 20 个 → 400） |
| GET | `/api/documents/{id}` | 内容 + 修订 |
| PUT | `/api/documents/{id}` | 保存，`base_revision` 不一致 → 409 |
| DELETE | `/api/documents/{id}` | 删除 |
| POST | `/api/rename/preview` | `{doc_id,line,col,new_name}` → 预览计划 |
| POST | `/api/rename/apply` | `{plan_id}` → 单事务应用或 409 整批拒绝 |
| WS | `/ws` | `hello` / `workspace_revision` / `diagnostics` |
