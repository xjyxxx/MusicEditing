# Maps assets (not vendored)

Offline map fonts (~100MB) and OBF extension packs were intentionally excluded
from this tree to keep MusicEditing lean.

## Enable full offline maps

1. Copy `src/maps/font` from upstream iPhotron into `third_party/iphoto/src/maps/font`
2. Copy `src/maps/tiles/extension` (or download the maps extension release) into
   `third_party/iphoto/src/maps/tiles/extension`

Upstream: https://github.com/OliverZhaohaibin/iPhotron-LocalPhotoAlbumManager

## Without these assets

- Place (地点) map still runs in MusicEditing hosted mode (CPU `MapWidget` + photo markers).
- City/place labels may warn (`QFont::setPointSizeF <= 0`) or look incomplete — that is expected.
- Photos without GPS show an empty-state banner; they will not appear as map markers.
- Optional HEIC / raw deps: `pip install -r client/scripts/requirements-iphoto.txt`

## Helper

```powershell
python scripts\sync_iphoto_vendor.py
python scripts\sync_iphoto_vendor.py --from E:\path\to\iPhotron-LocalPhotoAlbumManager
```
