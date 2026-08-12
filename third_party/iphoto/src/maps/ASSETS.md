# Maps assets (not vendored)

Offline map fonts (~100MB) and OBF extension packs were intentionally excluded
from this tree to keep MusicEditing lean.

To enable full offline maps:
1. Copy `src/maps/font` from upstream iPhotron into `third_party/iphoto/src/maps/font`
2. Copy `src/maps/tiles/extension` (or download the maps extension release) into `third_party/iphoto/src/maps/tiles/extension`

Upstream: https://github.com/OliverZhaohaibin/iPhotron-LocalPhotoAlbumManager
