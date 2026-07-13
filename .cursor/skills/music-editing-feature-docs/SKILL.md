---
name: music-editing-feature-docs
description: >-
  MusicEditing 项目功能开发与文档同步规范。在 MusicEditing 仓库中新增、修改或删除功能时，
  必须同步更新 docs/design/implementation_flow.md。Use when implementing features,
  adding modules, changing C++/Python architecture, or when the user asks to add
  functionality to this project.
---

# MusicEditing 功能开发 + 文档同步

## 核心规则

**每次加功能（或改架构/协议），代码改动与 `docs/design/implementation_flow.md` 更新必须在同一任务内完成。**  
不要只写代码不更新文档。

技术文档路径：`docs/design/implementation_flow.md`  
产品参考（只读对照）：`AI本地音视频处理工具-产品交互设计文档（开发落地版）.md`

---

## 何时必须更新文档

| 变更类型 | 必须更新的章节 |
|----------|----------------|
| 新功能 / 新页面 | §5 业务链路、§7 状态表；必要时新增 §5.x 小节 |
| 新 C++ API / CLI 命令 | §4 媒体引擎、§4.3 CLI 协议 |
| 新 Python Model/VM/View | §3 MVVM、§6 模块依赖 |
| 新 CMake 目标 / 第三方库 | §2.1 编译流程、§6 依赖关系 |
| 架构变更（如桥接方式） | §1 总体架构 |
| 功能从占位变为可用 | §7 状态 ✅；§8 扩展指南中删除或改写对应条目 |
| 新运行/测试命令 | §9 运行命令速查 |

---

## 开发完成检查清单

功能实现后，逐项确认：

```
- [ ] 代码已实现并通过编译/基本测试
- [ ] docs/design/implementation_flow.md 已更新
- [ ] §7「已实现 vs 待实现」状态已同步（✅ / ⏳）
- [ ] 若涉及用户操作，§5 补充完整交互链路（从 UI 到 C++）
- [ ] 若新增 media_cli 子命令，§4.3 补充 stdout/stderr 协议示例
- [ ] 若 §8 中的「待接入指南」已实现，移入 §5 并精简 §8
```

---

## 文档更新模板

### 1. 新业务功能（§5 新增小节）

```markdown
### 5.x <功能名>完整链路

对应产品文档 4.x 节。

\`\`\`
用户操作
  │
  ▼
View: <Page>._on_xxx()
  → ViewModel.<slot>()
      → MediaBridge.<method>() / AppLogic
          → media_cli <command>
              → C++ <API>
  → emit <Signal>
  │
  ▼
View 更新 UI
\`\`\`

**当前限制：**（如有）
```

### 2. CLI 协议（§4.3 追加）

```markdown
**<command> 命令：**
\`\`\`
media_cli <command> <args>
→ stdout:
  <COMMAND>_OK
  key=value
→ stderr: 日志（不影响协议解析）
\`\`\`
```

### 3. 状态表（§7 更新行）

```markdown
| <功能名> | ✅ / ⏳ | <实现位置或待办说明> |
```

---

## 项目架构速记（写文档时引用）

- **MVVM**：`models/` → `viewmodels/` → `ui/`
- **C++ 层**：`VideoDecoder` → `media_engine.dll` → `media_cli.exe`
- **桥接**：64 位 Python 通过 **subprocess** 调 32 位 `media_cli`（非 ctypes）
- **FFmpeg**：`third_party/ffmpeg/`，Win32 编译（`-A Win32`）
- **日志**：C++ 走 stderr；CLI 协议走 stdout

新增功能应遵循现有分层，避免 View 直接调用 FFmpeg 或 subprocess。

---

## 推荐开发顺序

1. 读 `implementation_flow.md` 确认现有链路与 §7 状态
2. 对照产品交互文档确认 UI/交互要求
3. 自下而上实现：C++ API → media_cli → MediaBridge → ViewModel → View
4. **更新 `implementation_flow.md`（本步骤不可跳过）**
5. 必要时更新 `README.md` 运行说明（仅当有新的 build/run 命令时）

---

## 示例：新增「批量导出」后文档应含

- §4：`media_clip_export` API 签名
- §4.3：`media_cli clip` 协议
- §5.4：从「批量导出」按钮到写文件的完整链路
- §6：`MediaBridge.export_clips` 依赖关系
- §7：`批量导出剪辑` 改为 ✅
- §8.2：删除或标注「已完成」
