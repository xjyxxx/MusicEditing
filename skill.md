# MusicEditing 项目 Skill

本仓库在 `.cursor/skills/` 下维护 Cursor Agent Skill，用于规范 AI 辅助开发时的行为。

## 可用 Skill

| Skill | 路径 | 用途 |
|-------|------|------|
| 功能开发 + 文档同步 | `.cursor/skills/music-editing-feature-docs/SKILL.md` | **每次加功能必须同步更新** `docs/design/` 对应专文与枢纽状态表 |

## 使用方式

在 Cursor 对话中开发新功能时，Agent 会自动匹配该 Skill；也可显式说明：

> 按项目 skill 规范，实现 XXX 功能并更新技术文档

## 技术文档

- 总索引：`docs/README.md`
- 枢纽（架构 / 状态 / 命令）：`docs/design/implementation_flow.md`
- 业务链路：`docs/design/feature_flows.md`
- MVVM / UI：`docs/design/mvvm_and_ui.md`
- 媒体引擎 / CLI：`docs/design/media_engine.md`
- 依赖与扩展：`docs/design/deps_and_extending.md`
- 播放器解码：`docs/design/player_decode_flow.md`
- 产品交互（对照用）：`AI本地音视频处理工具-产品交互设计文档（开发落地版）.md`
