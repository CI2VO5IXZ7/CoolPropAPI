"""湿空气物性计算 API.

调用约定：
- GET  /ha?<key1>=<v1>&<key2>=<v2>[&P=<Pa>]    任意 2 个状态参数 → 返回全部物性
- POST /ha/batch                                 批量计算
- GET  /ha/keys                                  支持的属性代码与单位说明
- GET  /health                                   健康检查
- GET  /                                         使用文档主页

P 默认 101325 Pa，可显式覆盖。温度统一 ℃，焓统一 kJ/(kg 干空气)。
"""

import math
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
import CoolProp.CoolProp as CP

app = FastAPI(
    title="湿空气物性计算 API",
    description="基于 FastAPI + CoolProp。给定任意 2 个状态参数，返回该状态点的全部湿空气物性。",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")

# --- 常量 ---

DEFAULT_PRESSURE_PA = 101325.0

# 接受的状态参数代码（不含 P 与 out_prop）
STATE_KEYS = {
    "T", "Tdb",      # 干球温度 ℃
    "B", "Twb",      # 湿球温度 ℃
    "D", "Tdp",      # 露点温度 ℃
    "R",             # 相对湿度 0~1
    "W",             # 含湿量 kg/kg 干空气
    "H", "Hda",      # 比焓 kJ/kg 干空气
    "V", "Vda",      # 比容 m^3/kg 干空气
    "S", "Sda",      # 比熵 J/(kg·K)
    "Y", "psi_w",    # 水蒸气摩尔分数
}

ALL_INPUT_KEYS = STATE_KEYS | {"P"}

TEMP_KEYS = {"T", "Tdb", "B", "Twb", "D", "Tdp"}
ENTHALPY_KEYS = {"H", "Hda", "Hha"}

# 输出全量状态时实际计算的字段（CoolProp 代码 → 单位描述）
OUTPUT_FIELDS = [
    ("T",   "℃"),
    ("Twb", "℃"),
    ("Tdp", "℃"),
    ("R",   "0~1"),
    ("W",   "kg/kg 干空气"),
    ("H",   "kJ/kg 干空气"),
    ("V",   "m^3/kg 干空气"),
    ("S",   "J/(kg·K)"),
    ("Y",   "mol/mol"),
]


# --- 单位换算 ---

def _to_si(prop: str, val: float) -> float:
    if prop in TEMP_KEYS:
        return val + 273.15
    if prop in ENTHALPY_KEYS:
        return val * 1000.0
    return val


def _from_si(prop: str, val: float) -> float:
    if prop in TEMP_KEYS:
        return val - 273.15
    if prop in ENTHALPY_KEYS:
        return val / 1000.0
    return val


def _clean_error(err: Exception) -> str:
    return str(err).split("\n")[0][:300]


# --- 核心计算 ---

def _compute_full_state(state_inputs: Dict[str, float], pressure: float) -> Dict[str, Optional[float]]:
    """给定 2 个状态参数 + 压力，返回完整状态字典。

    单个字段计算失败时返回 None，不阻断整体。
    """
    args: List[Any] = ["P", pressure]
    for k, v in state_inputs.items():
        args.extend([k, _to_si(k, float(v))])

    state: Dict[str, Optional[float]] = {}
    for prop, _unit in OUTPUT_FIELDS:
        try:
            si_val = CP.HAPropsSI(prop, *args)
            if isinstance(si_val, float) and not math.isfinite(si_val):
                state[prop] = None
            else:
                state[prop] = _from_si(prop, si_val)
        except Exception:
            state[prop] = None
    return state


def _validate_and_split(raw: Dict[str, str]) -> (Dict[str, float], float, bool):
    """从查询参数中分离状态参数与压力，返回 (state_inputs, pressure, p_is_default)。"""
    invalid = [k for k in raw if k not in ALL_INPUT_KEYS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"存在无效的属性代码: {invalid}。有效代码见 /ha/keys",
        )

    parsed: Dict[str, float] = {}
    for k, v in raw.items():
        try:
            parsed[k] = float(v)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"参数 {k} 的值 '{v}' 不是有效的数字")
        if not math.isfinite(parsed[k]):
            raise HTTPException(status_code=400, detail=f"参数 {k} 的数值无效: {v}")

    if "P" in parsed:
        pressure = parsed.pop("P")
        p_is_default = False
    else:
        pressure = DEFAULT_PRESSURE_PA
        p_is_default = True

    if len(parsed) != 2:
        raise HTTPException(
            status_code=400,
            detail=f"需要且仅需 2 个状态参数（除 P 之外），当前提供了 {len(parsed)} 个",
        )

    return parsed, pressure, p_is_default


# --- 路由 ---

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@app.get("/ha", summary="计算湿空气全量状态", tags=["HumidAir"])
async def humid_air_state(request: Request) -> Dict[str, Any]:
    raw = dict(request.query_params)
    state_inputs, pressure, p_is_default = _validate_and_split(raw)

    try:
        state = _compute_full_state(state_inputs, pressure)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算错误: {_clean_error(e)}")

    return {
        "inputs": state_inputs,
        "pressure": {"P": pressure, "default": p_is_default},
        "state": state,
    }


class BatchRequest(BaseModel):
    points: List[Dict[str, float]] = Field(
        ...,
        description="状态点列表。每个点是一个 {属性代码: 数值} 字典；需含 2 个状态参数，可选含 P。",
    )


@app.post("/ha/batch", summary="批量计算湿空气全量状态", tags=["HumidAir"])
async def humid_air_batch(req: BatchRequest) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for idx, point in enumerate(req.points):
        try:
            raw = {k: str(v) for k, v in point.items()}
            state_inputs, pressure, p_is_default = _validate_and_split(raw)
            state = _compute_full_state(state_inputs, pressure)
            results.append({
                "index": idx,
                "inputs": state_inputs,
                "pressure": {"P": pressure, "default": p_is_default},
                "state": state,
                "status": "success",
            })
        except HTTPException as he:
            results.append({"index": idx, "inputs": point, "error": he.detail, "status": "error"})
        except Exception as e:
            results.append({"index": idx, "inputs": point, "error": _clean_error(e), "status": "error"})

    return {"count": len(results), "results": results}


@app.get("/ha/keys", summary="查询所有受支持的属性代码与单位", tags=["HumidAir"])
async def list_keys() -> Dict[str, Any]:
    return {
        "state_keys": sorted(STATE_KEYS),
        "pressure_key": "P",
        "default_pressure_pa": DEFAULT_PRESSURE_PA,
        "output_fields": [{"key": k, "unit": u} for k, u in OUTPUT_FIELDS],
        "notes": [
            "调用 /ha 时传入恰好 2 个状态参数；P 缺省 101325 Pa，可显式覆盖。",
            "温度类（T/Tdb/B/Twb/D/Tdp）输入输出单位为 ℃。",
            "焓类（H/Hda）输入输出单位为 kJ/kg 干空气。",
            "压力 P 单位为 Pa；相对湿度 R 取值 0~1（小数，非百分数）。",
            "含湿量 W 单位为 kg 水蒸气 / kg 干空气。",
        ],
    }


@app.get("/health", summary="健康检查", tags=["System"])
async def health_check() -> Dict[str, Any]:
    return {"status": "ok", "service": "CoolProp API", "version": app.version}
