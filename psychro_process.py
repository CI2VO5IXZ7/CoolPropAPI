"""过程链纯函数。

仅作为 templates/ui.html 同名 JS 规则的参考实现与单测锁定，不被 HTTP 路由调用。
"""

import math
from typing import Any, Tuple


class ProcessInputError(ValueError):
    """过程输入不合法（网页侧提示，不进入 HTTP 路由）。"""


def _as_float(name: str, val: Any) -> float:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ProcessInputError(f"{name}不是有效数字")
    num = float(val)
    if not math.isfinite(num):
        raise ProcessInputError(f"{name}不是有效数字")
    return num


def rh_percent_to_fraction(percent: float) -> float:
    """相对湿度百分数 → API 使用的 0~1。"""
    num = _as_float("相对湿度", percent)
    if not 0 <= num <= 100:
        raise ProcessInputError("相对湿度须在 0~100% 之间")
    return num / 100.0


def mix_humidity_enthalpy(
    f: float, w1: float, h1: float, w2: float, h2: float
) -> Tuple[float, float]:
    """干空气质量分数 f=m1/(m1+m2) 下的混合含湿量与比焓。"""
    frac = _as_float("混合参数 f", f)
    hum1 = _as_float("混合参数 W1", w1)
    enth1 = _as_float("混合参数 H1", h1)
    hum2 = _as_float("混合参数 W2", w2)
    enth2 = _as_float("混合参数 H2", h2)
    if not 0 < frac < 1:
        raise ProcessInputError("混合质量分数 f 须在 0 与 1 之间（不含端点）")
    return frac * hum1 + (1 - frac) * hum2, frac * enth1 + (1 - frac) * enth2


def dry_air_mass_fraction(m1: float, m2: float) -> float:
    """两股干空气质量 → f=m1/(m1+m2)。"""
    a = _as_float("m1", m1)
    b = _as_float("m2", m2)
    if not (a > 0 and b > 0):
        raise ProcessInputError("两股风的干空气质量须为正数")
    return a / (a + b)


def validate_sensible_heat(t_s: float, t_out: float) -> None:
    start = _as_float("起点干球", t_s)
    end = _as_float("终点干球", t_out)
    if not end > start:
        raise ProcessInputError("等湿加热的终点干球须高于起点")


def validate_sensible_cool(t_s: float, tdp_s: float, t_out: float) -> None:
    start = _as_float("起点干球", t_s)
    dew = _as_float("起点露点", tdp_s)
    end = _as_float("终点干球", t_out)
    if not end < start:
        raise ProcessInputError("等湿冷却的终点干球须低于起点")
    if end < dew:
        raise ProcessInputError("终点干球低于露点，请改用冷却除湿")


def validate_isothermal_humid(current: float, target: float, kind: str) -> None:
    cur = _as_float("起点湿度", current)
    nxt = _as_float("终点湿度", target)
    if not nxt > cur:
        if kind == "R":
            raise ProcessInputError("等温加湿的终点相对湿度须高于起点")
        raise ProcessInputError("等温加湿的终点含湿量须高于起点")


def validate_adiabatic_target(r_s: float, r_out: float) -> None:
    start = _as_float("起点相对湿度", r_s)
    end = _as_float("终点相对湿度", r_out)
    if not 0 <= end <= 1:
        raise ProcessInputError("终点相对湿度须在 0~1 之间")
    if not end > start:
        raise ProcessInputError("绝热加湿的终点相对湿度须高于起点")


def validate_coil_outlet(t_s: float, t_coil: float) -> None:
    start = _as_float("起点干球", t_s)
    coil = _as_float("盘管出风干球", t_coil)
    if not coil < start:
        raise ProcessInputError("盘管出风干球须低于起点干球")


def validate_reheat(t_coil: float, t_reheat: float) -> None:
    coil = _as_float("盘管出风干球", t_coil)
    reheat = _as_float("再热干球", t_reheat)
    if not reheat > coil:
        raise ProcessInputError("再热温度须高于盘管出风干球")


def validate_dehumid(w_s: float, w_coil: float) -> None:
    """盘管出风含湿量须低于起点，否则未发生除湿。"""
    start = _as_float("起点含湿量", w_s)
    coil = _as_float("盘管出风含湿量", w_coil)
    if not coil < start:
        raise ProcessInputError("盘管出风含湿量不低于起点，未发生除湿，请降低 T_coil 或改用等湿冷却")
