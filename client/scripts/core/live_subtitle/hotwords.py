"""热词 / 场景词表（游戏直播、主播口癖）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Sequence


@dataclass
class HotwordLexicon:
    """简单词表；真实后端可映射为 ASR bias / WFST / 自定义 LM。"""

    words: List[str] = field(default_factory=list)

    @classmethod
    def from_csv(cls, text: str) -> "HotwordLexicon":
        parts = []
        for raw in (text or "").replace("，", ",").split(","):
            w = raw.strip()
            if w:
                parts.append(w)
        # 去重保序
        seen = set()
        uniq: List[str] = []
        for w in parts:
            key = w.lower()
            if key not in seen:
                seen.add(key)
                uniq.append(w)
        return cls(words=uniq)

    def extend(self, more: Iterable[str]) -> None:
        extra = HotwordLexicon.from_csv(",".join(more))
        for w in extra.words:
            if w.lower() not in {x.lower() for x in self.words}:
                self.words.append(w)

    def as_list(self) -> Sequence[str]:
        return list(self.words)
