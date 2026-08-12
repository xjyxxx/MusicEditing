# iPhotron / iPhoto 源码子树（vendor）

本目录嵌入上游 [iPhotron-LocalPhotoAlbumManager](https://github.com/OliverZhaohaibin/iPhotron-LocalPhotoAlbumManager) 的 `src/iPhoto` 与精简版 `src/maps`，供 MusicEditing「照片图库」一比一复用其浏览/编辑体验。

| 路径 | 说明 |
|------|------|
| `src/iPhoto/` | 完整 Python 包（图库、编辑、Live 配对、索引等） |
| `src/maps/` | 地图扩展 Python 代码（**不含** ~100MB font 与 OBF 扩展包） |
| `LICENSE` | 上游 MIT |
| `UPSTREAM_README.md` | 上游 README 快照 |
| `pyproject.toml` | 上游依赖声明（参考用） |

地图完整资源说明见 [`src/maps/ASSETS.md`](src/maps/ASSETS.md)。

## 与 MusicEditing 的边界

- **嵌入入口**：`client/scripts/ui/iphoto_host_page.py` + `core/iphoto_bootstrap.py`
- **视频播放**：Live Photo / 详情页内预览仍可用 iPhoto 自带 `VideoArea`；需要进本应用工作流时，回调 `VideoPlayerWidget` / 首页播放（**不修改** `media_player` 播放链路）
- **降级**：iPhoto 导入失败时回退到原有 `PhotoLibraryPage`

## 同步上游

从本地检出或 clone 更新：

```text
robocopy <upstream>\src\iPhoto third_party\iphoto\src\iPhoto /E
robocopy <upstream>\src\maps  third_party\iphoto\src\maps  /E /XD tiles font .idea
```

建议记录上游 commit / tag，避免无说明的大包进入仓库。
