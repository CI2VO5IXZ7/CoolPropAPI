from pathlib import Path

import pytest

from psychro_process import (
    ProcessInputError,
    dry_air_mass_fraction,
    mix_humidity_enthalpy,
    rh_percent_to_fraction,
    validate_adiabatic_target,
    validate_coil_outlet,
    validate_dehumid,
    validate_isothermal_humid,
    validate_reheat,
    validate_sensible_cool,
    validate_sensible_heat,
)


UI_MARKERS = [
    'id="pressure"',
    'id="t_min"',
    'id="t_max"',
    'id="d_max"',
    'id="single-key-1"',
    'id="single-val-1"',
    'id="single-key-2"',
    'id="single-go"',
    'id="add-point"',
    'id="clear-points"',
    'id="draw-series"',
    'id="proc-type"',
    'id="proc-go"',
    'value="sens_heat"',
    'value="sens_cool"',
    'value="isoth_humid"',
    'value="adiab_humid"',
    'value="cool_dehumid"',
    'value="mix"',
    "上移",
    "下移",
    "删除",
    "清空",
    "请求过于频繁",
    'q.set("connect", "1")',
    "rhPercentToFraction",
    "mixHumidityEnthalpy",
    "等湿加热的终点干球须高于起点",
    "终点干球低于露点，请改用冷却除湿",
    "盘管出风含湿量不低于起点，未发生除湿，请降低 T_coil 或改用等湿冷却",
    "混合质量分数 f 须在 0 与 1 之间（不含端点）",
    "绝热加湿",
    "等湿球",
    "等焓",
    "viewport",
]


def test_ensure_state_asserts_before_assign():
    text = (Path(__file__).resolve().parents[1] / "templates" / "ui.html").read_text(encoding="utf-8")
    start = text.index("async function ensureState")
    end = text.index("\n        function ", start)
    body = text[start:end]
    assert body.index("assertPlottable(") < body.index("point.state =")


def test_ui_page_has_controls(client):
    resp = client.get("/ui")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "lang=\"zh-CN\"" in resp.text or "lang='zh-CN'" in resp.text
    for marker in UI_MARKERS:
        assert marker in resp.text, marker
    assert "/ha/process" not in resp.text


def test_home_links_calculator_and_connect(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'href="/ui"' in resp.text
    assert "打开计算器" in resp.text
    assert "connect" in resp.text
    assert "/ha/batch" in resp.text


def test_rh_percent_and_mix():
    assert rh_percent_to_fraction(0) == 0
    assert rh_percent_to_fraction(50) == 0.5
    assert rh_percent_to_fraction(100) == 1
    with pytest.raises(ProcessInputError, match="0~100%"):
        rh_percent_to_fraction(100.1)
    with pytest.raises(ProcessInputError, match="不是有效数字"):
        rh_percent_to_fraction(float("nan"))

    w, h = mix_humidity_enthalpy(0.25, 0.008, 40, 0.016, 70)
    assert w == pytest.approx(0.014)
    assert h == pytest.approx(62.5)
    assert dry_air_mass_fraction(1, 3) == pytest.approx(0.25)
    with pytest.raises(ProcessInputError, match="不含端点"):
        mix_humidity_enthalpy(0, 0.01, 40, 0.02, 50)
    with pytest.raises(ProcessInputError, match="正数"):
        dry_air_mass_fraction(0, 1)


def test_process_guards():
    validate_sensible_heat(25, 35)
    with pytest.raises(ProcessInputError, match="等湿加热"):
        validate_sensible_heat(25, 25)

    validate_sensible_cool(25, 14, 18)
    with pytest.raises(ProcessInputError, match="冷却除湿"):
        validate_sensible_cool(25, 14, 10)
    with pytest.raises(ProcessInputError, match="等湿冷却"):
        validate_sensible_cool(25, 14, 30)

    validate_isothermal_humid(0.4, 0.7, "R")
    with pytest.raises(ProcessInputError, match="相对湿度"):
        validate_isothermal_humid(0.4, 0.4, "R")
    with pytest.raises(ProcessInputError, match="含湿量"):
        validate_isothermal_humid(0.008, 0.008, "W")

    validate_adiabatic_target(0.4, 0.95)
    with pytest.raises(ProcessInputError, match="高于起点"):
        validate_adiabatic_target(0.4, 0.3)

    validate_coil_outlet(28, 12)
    with pytest.raises(ProcessInputError, match="盘管出风"):
        validate_coil_outlet(28, 28)
    validate_reheat(12, 22)
    with pytest.raises(ProcessInputError, match="再热"):
        validate_reheat(12, 12)

    validate_dehumid(0.012, 0.008)
    with pytest.raises(ProcessInputError, match="未发生除湿"):
        validate_dehumid(0.010, 0.010)
    with pytest.raises(ProcessInputError, match="未发生除湿"):
        validate_dehumid(0.008, 0.012)
