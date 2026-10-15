"""湿空气物性计算 API.

调用约定：
- GET  /ha?<key1>=<v1>&<key2>=<v2>[&P=<Pa>]    任意 2 个状态参数 → 返回全部物性
- POST /ha/batch                                 批量计算
- GET  /ha/keys                                  支持的属性代码与单位说明
- GET  /health                                   健康检查
- GET  /                                         使用文档主页

P 默认 101325 Pa，可显式覆盖。温度统一 ℃，焓统一 kJ/(kg 干空气)。
输入越界、同义参数冲突、batch 超过 500 点均返回 400；默认每 IP 每分钟 60 次请求。
"""

import math
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware
from slowapi.util import get_remote_address
import CoolProp.CoolProp as CP

app = FastAPI(
    title="湿空气物性计算 API",
    description="基于 FastAPI + CoolProp。给定任意 2 个状态参数，返回该状态点的全部湿空气物性。",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

DEFAULT_RATE_LIMIT = "60/minute"


def _client_ip(request: Request) -> str:
    # 部署在反向代理（Zeabur）之后时，直连地址是代理，需取 X-Forwarded-For 首个地址
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return get_remote_address(request)


limiter = Limiter(key_func=_client_ip, default_limits=[DEFAULT_RATE_LIMIT], storage_uri="memory://")
app.state.limiter = limiter

app.add_middleware(SlowAPIASGIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": f"请求过于频繁，请稍后再试（限制：{exc.detail}/IP）"},
    )


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    if errors:
        first = errors[0]
        loc = ".".join(str(x) for x in first.get("loc", ()) if x != "body") or "请求"
        msg = f"请求参数格式错误: {loc} {first.get('msg', '')}".strip()
    else:
        msg = "请求参数格式错误"
    return JSONResponse(status_code=400, content={"detail": msg[:300]})

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

MAX_BATCH_POINTS = 500

# 同义参数组：同组内只能提供一个
SYNONYM_GROUPS = [
    ("T", "Tdb"),
    ("B", "Twb"),
    ("D", "Tdp"),
    ("H", "Hda"),
    ("V", "Vda"),
    ("S", "Sda"),
    ("Y", "psi_w"),
]

# 输入范围（含端点）：代码 → (下限, 上限, 单位)
P_RANGE = (50000.0, 110000.0, "Pa")
TEMP_RANGE = (-100.0, 200.0, "℃")
INPUT_RANGES: Dict[str, Tuple[float, float, str]] = {
    "P": P_RANGE,
    **{k: TEMP_RANGE for k in TEMP_KEYS},
    "R": (0.0, 1.0, ""),
    "W": (0.0, 0.1, "kg/kg 干空气"),
    "H": (-100.0, 500.0, "kJ/kg 干空气"),
    "Hda": (-100.0, 500.0, "kJ/kg 干空气"),
}

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


def _check_range(key: str, val: float) -> None:
    rng = INPUT_RANGES.get(key)
    if rng is None:
        return
    lo, hi, unit = rng
    if not lo <= val <= hi:
        raise HTTPException(
            status_code=400,
            detail=f"参数 {key} 的值 {val:g} 超出允许范围 [{lo:g}, {hi:g}] {unit}".rstrip(),
        )


def _validate_and_split(raw: Dict[str, str]) -> Tuple[Dict[str, float], float, bool]:
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
        _check_range(k, parsed[k])

    for a, b in SYNONYM_GROUPS:
        if a in parsed and b in parsed:
            raise HTTPException(status_code=400, detail=f"参数 {a} 与 {b} 为同义参数，不能同时提供")

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
        description=f"状态点列表（最多 {MAX_BATCH_POINTS} 个）。每个点是一个 {{属性代码: 数值}} 字典；需含 2 个状态参数，可选含 P。",
    )


def _compute_batch(points: List[Dict[str, float]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for idx, point in enumerate(points):
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
    return results


@app.post("/ha/batch", summary="批量计算湿空气全量状态", tags=["HumidAir"])
async def humid_air_batch(req: BatchRequest) -> Dict[str, Any]:
    if len(req.points) > MAX_BATCH_POINTS:
        raise HTTPException(
            status_code=400,
            detail=f"批量点数 {len(req.points)} 超过上限 {MAX_BATCH_POINTS}",
        )
    results = await run_in_threadpool(_compute_batch, req.points)
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
@limiter.exempt
async def health_check() -> Dict[str, Any]:
    return {"status": "ok", "service": "CoolProp API", "version": app.version}
