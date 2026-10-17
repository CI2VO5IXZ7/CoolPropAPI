import pytest

import chart

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_default_png(client):
    resp = client.get("/chart/hd")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["cache-control"] == "public, max-age=86400"
    assert resp.content.startswith(PNG_MAGIC)


def test_png_width(client):
    import struct

    resp = client.get("/chart/hd", params={"width": 600})
    assert resp.status_code == 200
    width, height = struct.unpack(">II", resp.content[16:24])
    assert width == 600 and height > 300


def test_svg_with_points(client):
    resp = client.get("/chart/hd", params={"fmt": "svg", "points": "25,0.5;30,0.6"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in resp.content[:2000]


def test_en_and_custom_range(client):
    resp = client.get(
        "/chart/hd",
        params={"lang": "en", "p": 80000, "t_min": 0, "t_max": 30, "d_max": 20, "points": "20,0.4"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-language"] == "en"
    assert resp.content.startswith(PNG_MAGIC)


@pytest.mark.parametrize(
    "params, needle",
    [
        ({"t_max": 999}, "t_max"),
        ({"t_min": -31}, "t_min"),
        ({"t_min": 20, "t_max": 25}, "跨度"),
        ({"t_min": 30, "t_max": 10}, "跨度"),
        ({"p": 49999}, "参数 p"),
        ({"p": 110001}, "参数 p"),
        ({"d_max": 4}, "d_max"),
        ({"d_max": 61}, "d_max"),
        ({"fmt": "jpg"}, "fmt"),
        ({"width": 599}, "width"),
        ({"width": 2401}, "width"),
        ({"lang": "fr"}, "lang"),
        ({"points": "25"}, "格式错误"),
        ({"points": "a,b"}, "格式错误"),
        ({"points": "25,1.5"}, "相对湿度"),
        ({"points": "80,0.5"}, "超出图幅"),
        ({"points": "40,1", "d_max": 10}, "含湿量"),
        ({"points": ";".join(["25,0.5"] * 11)}, "上限"),
        ({"width": "abc"}, "请求参数格式错误"),
    ],
)
def test_out_of_range_400(client, params, needle):
    resp = client.get("/chart/hd", params=params)
    assert resp.status_code == 400, resp.text
    assert needle in resp.json()["detail"]


def test_cjk_font_missing_falls_back_to_en(client, monkeypatch, caplog):
    monkeypatch.setattr(chart, "find_cjk_font", lambda: None)
    with caplog.at_level("WARNING", logger="coolpropapi.chart"):
        resp = client.get("/chart/hd", params={"lang": "zh", "width": 600, "points": "25,0.5"})
        base = client.get("/chart/hd", params={"lang": "zh", "width": 600})
    assert resp.status_code == 200 and base.status_code == 200
    assert resp.headers["content-language"] == "en"
    assert base.headers["content-language"] == "en"
    assert resp.content.startswith(PNG_MAGIC)
    assert "未找到中文字体" in caplog.text


@pytest.mark.filterwarnings("ignore:Glyph .* missing from font")
def test_zh_uses_cjk_font_when_available(client, monkeypatch):
    # 不依赖系统字体：用 matplotlib 自带 DejaVu 冒充“中文字体”，只验证 zh 路径不回退
    from matplotlib import font_manager
    from matplotlib.font_manager import FontProperties

    fake = font_manager.findfont(FontProperties(family="DejaVu Sans"))
    monkeypatch.setattr(chart, "find_cjk_font", lambda: fake)
    resp = client.get("/chart/hd", params={"width": 600, "fmt": "svg"})
    assert resp.status_code == 200
    assert resp.headers["content-language"] == "zh"


def test_chart_rate_limit_429(client):
    for _ in range(10):
        assert client.get("/chart/hd", params={"t_max": 999}).status_code == 400
    resp = client.get("/chart/hd")
    assert resp.status_code == 429
    assert "请求过于频繁" in resp.json()["detail"]


def test_acceptance_point_coordinates():
    """t=25 ℃ / φ=50% 应落在 d≈9.93 g/kg、h≈50.4 kJ/kg，画布 y = h - 2.5·d。"""
    w = chart._w(25.0, 0.5, 101325.0)
    d = w * 1000.0
    h = chart._h_tw(25.0, w, 101325.0)
    assert d == pytest.approx(9.93, abs=0.01)
    assert h == pytest.approx(50.4, abs=0.05)
    assert chart.to_canvas(d, h) == pytest.approx(h - 2.5 * d)


def test_isotherms_nearly_horizontal_isenthalps_slanted():
    geo = chart._geometry(101325.0, -10.0, 45.0, 30.0)
    # 等温线：d 从 0 到右边界，y 变化相对等焓线下降量很小且向右上倾
    i = int(len(geo.ts) * 0.6)
    dy_iso = geo.y_right[i] - geo.y0[i]
    assert 0 < dy_iso < 0.1 * chart.K * geo.d_right[i]
    # 等焓线画布斜率为 -K
    assert chart.to_canvas(10, 50) - chart.to_canvas(0, 50) == pytest.approx(-chart.K * 10)


def test_base_chart_cached():
    chart.clear_cache()
    params = chart.validate_params(**{**chart.DEFAULTS, "width": 600})
    a, _ = chart.render_chart(params)
    b, _ = chart.render_chart(params)
    assert a is b


def test_prewarm_fills_cache():
    import main

    chart.clear_cache()
    main._prewarm_chart()
    assert chart._render_base.cache_info().currsize == 1


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, False),
        ("", False),
        ("0", False),
        ("false", False),
        ("FALSE", False),
        ("no", False),
        ("off", False),
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("on", True),
        (" 1 ", True),
    ],
)
def test_parse_connect(raw, expected):
    assert chart.parse_connect(raw) is expected


@pytest.mark.parametrize("raw", ["2", "maybe", "connect", "1.0"])
def test_parse_connect_rejects(raw):
    with pytest.raises(chart.ChartParamError, match="connect"):
        chart.parse_connect(raw)


def test_series_label():
    assert chart.series_label(1, connect=False) == "1"
    assert chart.series_label(10, connect=False) == "10"
    assert chart.series_label(1, connect=True) == "A"
    assert chart.series_label(10, connect=True) == "J"
    assert chart.series_label(26, connect=True) == "Z"
    assert chart.series_label(27, connect=True) == "P27"


def _svg_norm(raw: bytes) -> bytes:
    # matplotlib 每次给 clip path / marker 一个新 id，其余内容应一致。
    import re
    return re.sub(br"\b[mp][0-9a-f]{8,}\b", b"ID", raw)


def test_connect_svg_png_and_default_has_no_line(client):
    common = {"width": 600, "points": "25,0.5;32,0.4"}
    plain = client.get("/chart/hd", params={**common, "fmt": "svg"})
    off = client.get("/chart/hd", params={**common, "fmt": "svg", "connect": "0"})
    linked = client.get("/chart/hd", params={**common, "fmt": "svg", "connect": "1"})
    png = client.get("/chart/hd", params={**common, "fmt": "png", "connect": "true"})
    assert plain.status_code == off.status_code == linked.status_code == png.status_code == 200
    assert plain.headers["content-type"].startswith("image/svg+xml")
    assert linked.headers["content-type"].startswith("image/svg+xml")
    assert png.headers["content-type"] == "image/png"
    assert _svg_norm(plain.content) == _svg_norm(off.content)
    assert _svg_norm(plain.content) != _svg_norm(linked.content)
    assert len(plain.content) > 1000 and len(linked.content) > 1000 and len(png.content) > 1000
    assert png.content.startswith(PNG_MAGIC)
    assert b"hd-connect" not in plain.content
    assert b"<!-- 1:" in plain.content and b"<!-- 2:" in plain.content
    assert b'id="hd-connect"' in linked.content
    assert b"hd-connect-arrow" in linked.content
    assert b"<!-- A:" in linked.content and b"<!-- B:" in linked.content
    assert b"<!-- 1:" not in linked.content
    assert b"#e67e22" in plain.content and b"#e67e22" in linked.content


def test_connect_invalid_400(client):
    resp = client.get("/chart/hd", params={"connect": "maybe", "width": 600})
    assert resp.status_code == 400
    assert "connect" in resp.json()["detail"]


def test_connect_without_points_matches_base(client):
    params = {"fmt": "svg", "width": 600}
    base = client.get("/chart/hd", params=params)
    linked = client.get("/chart/hd", params={**params, "connect": "1"})
    assert base.status_code == linked.status_code == 200
    assert len(base.content) > 1000 and len(linked.content) > 1000
    assert _svg_norm(base.content) == _svg_norm(linked.content)
    assert b"hd-connect" not in base.content


def test_connect_render_does_not_enter_base_cache():
    chart.clear_cache()
    params = chart.validate_params(**{**chart.DEFAULTS, "fmt": "svg", "width": 600})
    base, _ = chart.render_chart(params)
    misses = chart._render_base.cache_info().misses
    linked, _ = chart.render_chart(params, ((25.0, 0.5), (32.0, 0.4)), connect=True)
    info = chart._render_base.cache_info()
    assert info.currsize == 1
    assert info.misses == misses
    again, _ = chart.render_chart(params)
    assert again is base
    assert linked is not base
    assert b"hd-connect" in linked
    assert b"hd-connect" not in base
