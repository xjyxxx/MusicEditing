# Upstream pin

- Source: https://github.com/OliverZhaohaibin/iPhotron-LocalPhotoAlbumManager
- Local snapshot used for initial vendor copy: `E:\FFmpegxuexi\iPhotron-LocalPhotoAlbumManager-main`
- Upstream package version (pyproject): 6.6.8
- Vendor layout: `src/iPhoto` full; `src/maps` without `font/` and `tiles/extension` binaries
- MusicEditing integration: `client/scripts/ui/iphoto_host_page.py` + `core/iphoto_bootstrap.py`
- Player boundary: do not replace MusicEditing `VideoPlayerWidget` / `media_player.exe`
