# Upstream pin

- Source: https://github.com/OliverZhaohaibin/iPhotron-LocalPhotoAlbumManager
- Upstream package version (pyproject): 6.6.8
- Vendor layout: `src/iPhoto` full; `src/maps` without `font/` and `tiles/extension` binaries
- Last checked: 2026-08-12 15:38 UTC
- Snapshot stats: iPhoto files≈906; maps files≈51; maps/font=no
- MusicEditing integration: `client/scripts/ui/iphoto_host_page.py` + `core/iphoto_bootstrap.py`
- Player boundary: do not replace MusicEditing `VideoPlayerWidget` / `media_player.exe`
- Sync helper: `python scripts/sync_iphoto_vendor.py`（`--from` 复制本地上游；`--write-pin` 刷新本文件）
- Maps assets: see `src/maps/ASSETS.md`
