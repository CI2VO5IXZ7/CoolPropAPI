"""国标样式湿空气 h-d 焓湿图（斜角坐标）。

横轴为含湿量 d (g/kg 干空气)；画布纵坐标 y = h - K·d（K ≈ 2.5，即 r0≈2501 kJ/kg ÷ 1000），
使等温线近似水平、等焓线向右下斜交（约 135°）。所有数值均来自 CoolProp HAPropsSI，与 /ha 同源。
"""

import io
import logging
import math
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import CoolProp.CoolProp as CP  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.patches import Polygon  # noqa: E402

logger = logging.getLogger("coolpropapi.chart")

K = 2.5

DEFAULTS = {
    "p": 101325.0,
    "t_min": -10.0,
    "t_max": 45.0,
    "d_max": 30.0,
    "fmt": "png",
    "width": 1200,
    "lang": "zh",
}
P_RANGE = (50000.0, 110000.0)
T_RANGE = (-30.0, 60.0)
MIN_T_SPAN = 10.0
D_MAX_RANGE = (5.0, 60.0)
WIDTH_RANGE = (600, 2400)
MAX_POINTS = 10
FORMATS = ("png", "svg")
LANGS = ("zh", "en")

CJK_FONT_FAMILIES = ("Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", "WenQuanYi Zen Hei")

FIG_WIDTH_IN = 12.0
MARGIN_L, MARGIN_R, MARGIN_B, MARGIN_T = 1.0, 0.5, 0.8, 1.1

# 同一时刻最多 2 个出图任务
_render_slots = threading.BoundedSemaphore(2)

LABELS = {
    "zh": {
        "title": "湿空气焓湿图（h-d 图）   B = {p:.0f} Pa",
        "x": "含湿量 d / (g/kg 干空气)",
        "y": "干球温度 t / ℃",
        "h": "焓 h / (kJ/kg 干空气)",
        "phi": "φ={v:d}%",
        "deg": "℃",
        "source": "数据来源：CoolProp HAPropsSI",
    },
    "en": {
        "title": "Psychrometric chart (h-d)   B = {p:.0f} Pa",
        "x": "Humidity ratio d / (g/kg dry air)",
        "y": "Dry-bulb temperature t / °C",
        "h": "Enthalpy h / (kJ/kg dry air)",
        "phi": "{v:d}%",
        "deg": "°C",
        "source": "Data: CoolProp HAPropsSI",
    },
}


class ChartParamError(ValueError):
    """图表参数不合法（应映射为 HTTP 400）。"""


@dataclass(frozen=True)
class ChartParams:
    p: float
    t_min: float
    t_max: float
    d_max: float
    fmt: str
    width: int
    lang: str


# --- 参数校验 ---

def validate_params(p: float, t_min: float, t_max: float, d_max: float, fmt: str, width: int, lang: str) -> ChartParams:
    for name, val in (("p", p), ("t_min", t_min), ("t_max", t_max), ("d_max", d_max)):
        if not math.isfinite(val):
            raise ChartParamError(f"参数 {name} 的数值无效: {val}")
    if not P_RANGE[0] <= p <= P_RANGE[1]:
        raise ChartParamError(f"参数 p 的值 {p:g} 超出允许范围 [{P_RANGE[0]:g}, {P_RANGE[1]:g}] Pa")
    for name, val in (("t_min", t_min), ("t_max", t_max)):
        if not T_RANGE[0] <= val <= T_RANGE[1]:
            raise ChartParamError(f"参数 {name} 的值 {val:g} 超出允许范围 [{T_RANGE[0]:g}, {T_RANGE[1]:g}] ℃")
    if t_max - t_min < MIN_T_SPAN:
        raise ChartParamError(f"温度范围需满足 t_min < t_max 且跨度 ≥ {MIN_T_SPAN:g} ℃，当前 [{t_min:g}, {t_max:g}]")
    if not D_MAX_RANGE[0] <= d_max <= D_MAX_RANGE[1]:
        raise ChartParamError(f"参数 d_max 的值 {d_max:g} 超出允许范围 [{D_MAX_RANGE[0]:g}, {D_MAX_RANGE[1]:g}] g/kg")
    if fmt not in FORMATS:
        raise ChartParamError(f"参数 fmt 只能为 {' | '.join(FORMATS)}，当前为 '{fmt}'")
    if not WIDTH_RANGE[0] <= width <= WIDTH_RANGE[1]:
        raise ChartParamError(f"参数 width 的值 {width} 超出允许范围 [{WIDTH_RANGE[0]}, {WIDTH_RANGE[1]}] px")
    if lang not in LANGS:
        raise ChartParamError(f"参数 lang 只能为 {' | '.join(LANGS)}，当前为 '{lang}'")
    return ChartParams(float(p), float(t_min), float(t_max), float(d_max), fmt, int(width), lang)


def parse_points(raw: Optional[str], params: ChartParams) -> Tuple[Tuple[float, float], ...]:
    """解析 'T,R;T,R'（℃, 0~1），并检查是否落在图幅内。"""
    if raw is None or raw.strip() == "":
        return ()
    items = [s for s in raw.split(";") if s.strip()]
    if len(items) > MAX_POINTS:
        raise ChartParamError(f"状态点数 {len(items)} 超过上限 {MAX_POINTS}")
    points: List[Tuple[float, float]] = []
    for idx, item in enumerate(items, start=1):
        parts = item.split(",")
        try:
            if len(parts) != 2:
                raise ValueError
            t, r = float(parts[0]), float(parts[1])
        except ValueError:
            raise ChartParamError(f"状态点 {idx} 格式错误: '{item.strip()}'，应为 'T,R'（℃, 0~1），多个点用 ';' 分隔")
        if not (math.isfinite(t) and math.isfinite(r)):
            raise ChartParamError(f"状态点 {idx} 的数值无效: '{item.strip()}'")
        if not params.t_min <= t <= params.t_max:
            raise ChartParamError(f"状态点 {idx} 的温度 {t:g} ℃ 超出图幅 [{params.t_min:g}, {params.t_max:g}] ℃")
        if not 0.0 <= r <= 1.0:
            raise ChartParamError(f"状态点 {idx} 的相对湿度 {r:g} 超出允许范围 [0, 1]")
        d = _w(t, r, params.p) * 1000.0
        if not math.isfinite(d) or d > params.d_max:
            raise ChartParamError(f"状态点 {idx} 的含湿量 {d:.2f} g/kg 超出图幅 d_max={params.d_max:g} g/kg")
        points.append((t, r))
    return tuple(points)


# --- 字体 ---

@lru_cache(maxsize=1)
def find_cjk_font() -> Optional[str]:
    """返回可用中文字体文件路径；找不到时返回 None。"""
    for family in CJK_FONT_FAMILIES:
        try:
            return font_manager.findfont(FontProperties(family=family), fallback_to_default=False)
        except ValueError:
            continue
    return None


def resolve_lang(lang: str) -> str:
    if lang == "zh" and find_cjk_font() is None:
        logger.warning("未找到中文字体（%s），h-d 图标签回退为英文", ", ".join(CJK_FONT_FAMILIES))
        return "en"
    return lang


# --- 物性（CoolProp） ---

def _w(t: float, r: float, p: float) -> float:
    try:
        return CP.HAPropsSI("W", "T", t + 273.15, "R", r, "P", p)
    except Exception:
        return float("nan")


def _h_tw(t: float, w: float, p: float) -> float:
    """kJ/kg 干空气。"""
    try:
        return CP.HAPropsSI("H", "T", t + 273.15, "W", w, "P", p) / 1000.0
    except Exception:
        return float("nan")


def _h_tr(t: float, r: float, p: float) -> float:
    try:
        return CP.HAPropsSI("H", "T", t + 273.15, "R", r, "P", p) / 1000.0
    except Exception:
        return float("nan")


def to_canvas(d: float, h: float) -> float:
    return h - K * d


@dataclass(frozen=True)
class Geometry:
    ts: np.ndarray        # 细分温度网格
    y0: np.ndarray        # d=0 处等温线纵坐标
    d_right: np.ndarray   # 每个温度下有效区右边界 min(d_sat, d_max)
    y_right: np.ndarray
    d_sat: np.ndarray
    h_right: np.ndarray
    phi_curves: Tuple[Tuple[int, np.ndarray, np.ndarray], ...]  # (φ%, d, y)


@lru_cache(maxsize=32)
def _geometry(p: float, t_min: float, t_max: float, d_max: float) -> Geometry:
    n = int(round((t_max - t_min) / 0.25)) + 1
    ts = np.linspace(t_min, t_max, n)
    y0 = np.array([_h_tw(t, 0.0, p) for t in ts])
    d_sat = np.array([_w(t, 1.0, p) * 1000.0 for t in ts])
    d_right = np.minimum(d_sat, d_max)
    h_right = np.array([_h_tw(t, d / 1000.0, p) for t, d in zip(ts, d_right)])
    y_right = h_right - K * d_right

    phi_ts = ts[::2] if len(ts) > 2 else ts
    curves = []
    for pct in range(10, 101, 10):
        r = pct / 100.0
        d = np.array([_w(t, r, p) * 1000.0 for t in phi_ts])
        h = np.array([_h_tr(t, r, p) for t in phi_ts])
        curves.append((pct, d, h - K * d))
    return Geometry(ts, y0, d_right, y_right, d_sat, h_right, tuple(curves))


# --- 出图 ---

def _iso_t_step(span: float) -> Tuple[float, float]:
    """(细线间隔, 刻度/加粗间隔)。"""
    return (1.0, 5.0) if span <= 60 else (2.0, 10.0)


def _d_step(d_max: float) -> Tuple[float, float]:
    if d_max <= 10:
        return 0.5, 1.0
    if d_max <= 30:
        return 1.0, 5.0
    return 2.0, 10.0


def _render(params: ChartParams, points: Sequence[Tuple[float, float]]) -> bytes:
    p, t_min, t_max, d_max = params.p, params.t_min, params.t_max, params.d_max
    geo = _geometry(p, t_min, t_max, d_max)
    lab = LABELS[params.lang]

    font_path = find_cjk_font() if params.lang == "zh" else None

    def fp(size: float, weight: str = "normal") -> FontProperties:
        if font_path:
            return FontProperties(fname=font_path, size=size, weight=weight)
        return FontProperties(size=size, weight=weight)

    y_lo = float(np.nanmin(geo.y0))
    y_hi = float(np.nanmax([geo.y0[-1], geo.y_right[-1]]))
    y_span = y_hi - y_lo
    y_bottom = y_lo - 0.03 * y_span
    y_top = y_hi + 0.06 * y_span

    # 使等焓线在画面上约 45° 向右下（与 d 轴斜交约 135°）
    axes_w = FIG_WIDTH_IN - MARGIN_L - MARGIN_R
    axes_h = axes_w * (y_top - y_bottom) / (K * d_max)
    axes_h = min(max(axes_h, 0.5 * axes_w), 1.4 * axes_w)
    fig_h = axes_h + MARGIN_B + MARGIN_T
    dpi = params.width / FIG_WIDTH_IN

    fig = Figure(figsize=(FIG_WIDTH_IN, fig_h), dpi=dpi)
    ax = fig.add_axes((MARGIN_L / FIG_WIDTH_IN, MARGIN_B / fig_h, axes_w / FIG_WIDTH_IN, axes_h / fig_h))
    ax.set_xlim(0, d_max)
    ax.set_ylim(y_bottom, y_top)

    # 有效区（未饱和、图幅内）作为所有线族的裁剪区域
    poly = np.vstack([
        np.column_stack([np.zeros_like(geo.ts), geo.y0]),
        np.column_stack([geo.d_right, geo.y_right])[::-1],
    ])
    poly = poly[np.all(np.isfinite(poly), axis=1)]
    region = Polygon(poly, closed=True, facecolor="#fbfdff", edgecolor="none", zorder=0)
    ax.add_patch(region)

    def clipped(artists):
        for a in artists:
            a.set_clip_path(region)

    # 等 d（竖直线）
    d_minor, d_major = _d_step(d_max)
    for d in np.arange(d_minor, d_max + 1e-9, d_minor):
        major = abs(d / d_major - round(d / d_major)) < 1e-9
        clipped(ax.plot([d, d], [y_bottom, y_top], color="#9bb7d4", lw=0.8 if major else 0.4, zorder=1))

    # 等 t（近水平）
    t_minor, t_major = _iso_t_step(t_max - t_min)
    t_ticks, y_ticks = [], []
    t = math.ceil(t_min / t_minor) * t_minor
    while t <= t_max + 1e-9:
        major = abs(t / t_major - round(t / t_major)) < 1e-9
        d_end = min(_w(t, 1.0, p) * 1000.0, d_max)
        ds = np.linspace(0.0, d_end, 4)
        ys = np.array([_h_tw(t, d / 1000.0, p) for d in ds]) - K * ds
        bold = abs(t / 10.0 - round(t / 10.0)) < 1e-9
        clipped(ax.plot(ds, ys, color="#c0392b", lw=1.1 if bold else (0.6 if major else 0.3), zorder=2))
        if major:
            t_ticks.append(t)
            y_ticks.append(ys[0])
        t += t_minor
    ax.set_yticks(y_ticks)
    ax.set_yticklabels([f"{v:g}" for v in t_ticks])

    # 等 h（斜线，向右下）
    h_lo = y_lo
    h_hi = float(np.nanmax(geo.h_right))
    top_y0, top_d1, top_y1 = geo.y0[-1], geo.d_right[-1], geo.y_right[-1]
    top_slope = (top_y1 - top_y0) / top_d1 if top_d1 > 0 else 0.0
    h_angle = math.degrees(math.atan2(-K, 1.0))
    for h in np.arange(math.ceil(h_lo / 10.0) * 10.0, h_hi + 1e-9, 10.0):
        ds = np.array([0.0, d_max])
        clipped(ax.plot(ds, h - K * ds, color="#2c7a3f", lw=0.6, zorder=2))
        # 标注在有效区左上外侧（左边界内侧或上边界外侧）
        if h <= top_y0:
            lx, ly, va = 0.25, h - K * 0.25, "bottom"
        else:
            d_e = (h - top_y0) / (K + top_slope)
            if d_e > top_d1:
                continue
            lx, ly, va = d_e, top_y0 + top_slope * d_e + 0.004 * y_span, "bottom"
        ax.text(lx, ly, f"{h:g}", color="#2c7a3f", rotation=h_angle, rotation_mode="anchor",
                transform_rotates_text=True, ha="left", va=va, fontproperties=fp(7.5), clip_on=False, zorder=4)

    # 等 φ
    for pct, ds, ys in geo.phi_curves:
        sat = pct == 100
        clipped(ax.plot(ds, ys, color="#1f4e8c", lw=1.8 if sat else 0.7, zorder=3))
        ok = np.isfinite(ds) & np.isfinite(ys) & (ds <= d_max * 0.97)
        if not ok.any():
            continue
        i = int(np.nonzero(ok)[0][-1])
        if sat:
            i = int(np.nonzero(ok)[0][len(np.nonzero(ok)[0]) * 2 // 3])
        ax.text(ds[i], ys[i], lab["phi"].format(v=pct), color="#1f4e8c", ha="right", va="bottom",
                fontproperties=fp(8, "bold" if sat else "normal"), zorder=4,
                bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.75))

    # 状态点
    for idx, (t, r) in enumerate(points, start=1):
        w = _w(t, r, p)
        d = w * 1000.0
        h = _h_tw(t, w, p)
        y = to_canvas(d, h)
        ax.plot([d], [y], marker="o", ms=6, color="#e67e22", mec="black", mew=0.8, zorder=6)
        ax.annotate(
            f"{idx}: {t:g}{lab['deg']} / {r * 100:g}%\nd={d:.2f} g/kg, h={h:.1f} kJ/kg",
            xy=(d, y), xytext=(8, 8), textcoords="offset points", fontproperties=fp(8),
            zorder=7, bbox=dict(boxstyle="round,pad=0.25", fc="#fff8e7", ec="#e67e22", lw=0.6),
        )

    ax.set_xticks(np.arange(0, d_max + 1e-9, d_major))
    ax.set_xlabel(lab["x"], fontproperties=fp(10))
    ax.set_ylabel(lab["y"], fontproperties=fp(10))
    ax.tick_params(labelsize=8)
    ax.set_title(lab["title"].format(p=p), fontproperties=fp(13, "bold"), pad=26)
    ax.text(0.005, 1.035, lab["h"], transform=ax.transAxes, ha="left", va="bottom",
            color="#2c7a3f", fontproperties=fp(9), clip_on=False)
    fig.text(1 - 0.1 / FIG_WIDTH_IN, 0.15 / fig_h, lab["source"], ha="right", va="bottom",
             color="#888888", fontproperties=fp(7))

    buf = io.BytesIO()
    if params.fmt == "svg":
        fig.savefig(buf, format="svg", metadata={"Date": None})
    else:
        fig.savefig(buf, format="png", dpi=dpi)
    return buf.getvalue()


@lru_cache(maxsize=32)
def _render_base(params: ChartParams) -> bytes:
    return _render(params, ())


def render_chart(params: ChartParams, points: Sequence[Tuple[float, float]] = ()) -> Tuple[bytes, ChartParams]:
    """返回 (图像字节, 实际使用的参数)。中文字体缺失时 lang 回退为 en。"""
    eff_lang = resolve_lang(params.lang)
    if eff_lang != params.lang:
        params = ChartParams(params.p, params.t_min, params.t_max, params.d_max, params.fmt, params.width, eff_lang)
    with _render_slots:
        if not points:
            return _render_base(params), params
        return _render(params, tuple(points)), params


def clear_cache() -> None:
    _render_base.cache_clear()
    find_cjk_font.cache_clear()


def media_type(fmt: str) -> str:
    return "image/svg+xml" if fmt == "svg" else "image/png"
