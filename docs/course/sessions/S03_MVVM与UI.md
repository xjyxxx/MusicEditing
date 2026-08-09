# S03 — PySide6 MVVM 与 Studio 页体系

**时长**：90–120 分钟 · **模块**：B 架构

## 本期目标

能在 `ui/` / `viewmodels/` / `models/` 之间定位改动点；理解懒加载页与菜单索引稳定性。

## 硬核点

- View ←Signal/Slot→ MainViewModel ←→ dataclass models  
- `workflow_link.TAB_*` 勿乱改号（接力 / 菜单依赖）  
- 页懒创建 + 空闲预热；`studio_kit` 滚动壳防裁半  
- 长路径：`ElidedPathLabel`；GroupBox 标题留白  

## Lab

改一处 UI 文案 → 对照 `.cursor/skills/music-editing-feature-docs`：要不要动 feature_flows / 枢纽状态表。

## 对照阅读

- `mvvm_and_ui.md` · `workflow_link.py`
