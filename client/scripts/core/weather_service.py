"""本地天气：按本机公网 IP 定位城市 + Open-Meteo 当前天气（免 Key）"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

from core.app_logger import setup_logging

log = setup_logging("Weather")

# WMO Weather interpretation codes → 简中
_WEATHER_TEXT = {
    0: "晴",
    1: "晴间多云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "大毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "小阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷阵雨",
    96: "雷阵雨伴冰雹",
    99: "强雷暴冰雹",
}

_UA = "MusicEditing/1.0 (local desktop; weather status)"


@dataclass
class WeatherInfo:
    city: str
    temperature_c: float
    weather_code: int
    weather_text: str
    humidity: Optional[int] = None
    wind_kmh: Optional[float] = None
    latitude: float = 0.0
    longitude: float = 0.0


@dataclass(frozen=True)
class WeatherMood:
    """今日氛围：天气 → 播放器 OpenCV 滤镜推荐（趣味彩蛋）。"""

    filter_mode: str  # 对应 VideoPlayer 下拉 data：clahe / film / …
    label: str        # 状态栏短标签：明亮 / 胶片
    reason: str       # tooltip / 底栏文案


def recommend_mood(weather_code: int) -> Optional[WeatherMood]:
    """晴天→明亮(CLAHE)，雨天→胶片；其它天气不推荐。"""
    code = int(weather_code)
    # WMO: 0 晴, 1 晴间多云
    if code in (0, 1):
        return WeatherMood(
            filter_mode="clahe",
            label="明亮",
            reason="晴天适合明亮预览（CLAHE）",
        )
    # 毛毛雨/雨/冻雨(50–69)、阵雨(80–82)、雷暴(≥95)
    if (50 <= code < 70) or (80 <= code <= 82) or code >= 95:
        return WeatherMood(
            filter_mode="film",
            label="胶片",
            reason="雨天试试胶片滤镜",
        )
    return None


def weather_code_text(code: int) -> str:
    if code in _WEATHER_TEXT:
        return _WEATHER_TEXT[code]
    if 0 <= code <= 3:
        return "多云"
    if 50 <= code < 70:
        return "雨"
    if 70 <= code < 80:
        return "雪"
    if code >= 95:
        return "雷雨"
    return "未知"


def _http_raw(url: str, timeout: float = 5.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _http_json(url: str, timeout: float = 5.0) -> dict:
    raw = _http_raw(url, timeout=timeout)
    data = json.loads(raw.decode("utf-8", errors="replace"))
    if not isinstance(data, dict):
        raise RuntimeError("unexpected json")
    return data


def _clean_city(name: str) -> str:
    s = (name or "").strip()
    if not s:
        return ""
    # 去掉常见后缀，状态栏更短
    for suffix in ("市", "地区", "自治州", "盟", "特别行政区"):
        if s.endswith(suffix) and len(s) > len(suffix) + 1:
            s = s[: -len(suffix)]
            break
    return s


def _geocode_city(city: str, timeout: float = 5.0) -> Optional[tuple[float, float]]:
    """城市名 → 经纬度（Open-Meteo Geocoding）"""
    q = urllib.parse.urlencode({
        "name": city,
        "count": 1,
        "language": "zh",
        "format": "json",
    })
    data = _http_json(f"https://geocoding-api.open-meteo.com/v1/search?{q}", timeout=timeout)
    results = data.get("results") or []
    if not results:
        return None
    hit = results[0]
    return float(hit["latitude"]), float(hit["longitude"])


def _reverse_city_zh(lat: float, lon: float, timeout: float = 5.0) -> str:
    """经纬度 → 中文城市名（Nominatim）"""
    q = urllib.parse.urlencode({
        "lat": f"{lat:.4f}",
        "lon": f"{lon:.4f}",
        "format": "json",
        "zoom": 10,
        "accept-language": "zh-CN",
    })
    data = _http_json(f"https://nominatim.openstreetmap.org/reverse?{q}", timeout=timeout)
    addr = data.get("address") or {}
    for key in ("city", "town", "municipality", "county", "state_district", "state"):
        val = addr.get(key)
        if isinstance(val, str) and val.strip():
            return _clean_city(val)
    display = data.get("display_name") or ""
    if display:
        return _clean_city(display.split(",")[0])
    return ""


def _locate_pconline(timeout: float = 5.0) -> Optional[tuple[str, float, float]]:
    """国内 IP 库：中文省/市，再地理编码拿坐标。"""
    raw = _http_raw("https://whois.pconline.com.cn/ipJson.jsp?json=true", timeout=timeout)
    text = raw.decode("gbk", errors="replace")
    # 偶发 JSONP / 前缀噪声
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    data = json.loads(m.group(0))
    city = _clean_city(str(data.get("city") or ""))
    pro = _clean_city(str(data.get("pro") or ""))
    label = city or pro
    if not label or label in ("", "本机地址", "局域网"):
        return None
    # 「XX省」仅作兜底查询名
    query = city or pro
    coords = _geocode_city(query, timeout=timeout)
    if not coords and pro and city:
        coords = _geocode_city(f"{pro}{city}", timeout=timeout)
    if not coords:
        return None
    return label, coords[0], coords[1]


def _locate_ip_api(timeout: float = 5.0) -> Optional[tuple[str, float, float]]:
    q = urllib.parse.urlencode({
        "fields": "status,message,country,regionName,city,lat,lon",
        "lang": "zh-CN",
    })
    data = _http_json(f"http://ip-api.com/json/?{q}", timeout=timeout)
    if data.get("status") != "success" or data.get("lat") is None:
        return None
    lat, lon = float(data["lat"]), float(data["lon"])
    city = _clean_city(str(data.get("city") or data.get("regionName") or ""))
    # 尽量换成中文地名
    zh = _reverse_city_zh(lat, lon, timeout=timeout)
    if zh:
        city = zh
    if not city:
        city = "本地"
    return city, lat, lon


def _locate_ipwho(timeout: float = 5.0) -> Optional[tuple[str, float, float]]:
    data = _http_json("https://ipwho.is/", timeout=timeout)
    if not data.get("success") or data.get("latitude") is None:
        return None
    lat, lon = float(data["latitude"]), float(data["longitude"])
    zh = _reverse_city_zh(lat, lon, timeout=timeout)
    if zh:
        return zh, lat, lon
    region = data.get("region")
    if isinstance(region, dict):
        region_name = region.get("name")
    else:
        region_name = region
    city = _clean_city(str(data.get("city") or region_name or data.get("country") or "本地"))
    return city or "本地", lat, lon


def locate_by_ip(timeout: float = 5.0) -> tuple[str, float, float]:
    """按本机出口 IP 粗定位本地城市，返回 (城市名, lat, lon)。"""
    errors: list[str] = []
    for name, fn in (
        ("pconline", _locate_pconline),
        ("ip-api", _locate_ip_api),
        ("ipwho", _locate_ipwho),
    ):
        try:
            hit = fn(timeout=timeout)
            if hit:
                log.info("定位成功 source=%s city=%s", name, hit[0])
                return hit
            errors.append(f"{name}: empty")
        except Exception as e:
            errors.append(f"{name}: {e}")
            log.debug("定位失败 %s: %s", name, e)
    raise RuntimeError("; ".join(errors) or "locate failed")


def fetch_current_weather(lat: float, lon: float, timeout: float = 5.0) -> WeatherInfo:
    q = urllib.parse.urlencode({
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "timezone": "auto",
    })
    data = _http_json(f"https://api.open-meteo.com/v1/forecast?{q}", timeout=timeout)
    cur = data.get("current") or {}
    code = int(cur.get("weather_code", -1))
    temp = float(cur.get("temperature_2m", 0.0))
    humidity = cur.get("relative_humidity_2m")
    wind = cur.get("wind_speed_10m")
    return WeatherInfo(
        city="",
        temperature_c=temp,
        weather_code=code,
        weather_text=weather_code_text(code),
        humidity=int(humidity) if humidity is not None else None,
        wind_kmh=float(wind) if wind is not None else None,
        latitude=lat,
        longitude=lon,
    )


def fetch_local_weather(timeout: float = 5.0) -> WeatherInfo:
    city, lat, lon = locate_by_ip(timeout=timeout)
    info = fetch_current_weather(lat, lon, timeout=timeout)
    info.city = city
    log.info(
        "天气 %s %.0f°C code=%s (%.2f,%.2f)",
        city, info.temperature_c, info.weather_code, lat, lon,
    )
    return info


def format_status_text(info: WeatherInfo, *, with_mood: bool = True) -> str:
    base = f"{info.city} {info.weather_text} {info.temperature_c:.0f}°C"
    if not with_mood:
        return base
    mood = recommend_mood(info.weather_code)
    if mood:
        return f"{base} · {mood.label}"
    return base


def format_status_error(err: str | BaseException | None = None) -> str:
    _ = err
    return "天气: 暂不可用"
