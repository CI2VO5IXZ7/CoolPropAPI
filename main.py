import math
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import CoolProp.CoolProp as CP

app = FastAPI(
    title="湿空气物性计算 API",
    description="基于 Python FastAPI 和 CoolProp 的湿空气物性计算服务，专为焓湿图计算设计。",
    version="1.1.0",
    docs_url=None,
    redoc_url=None,
)

# 允许跨域，方便前端绘图调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")

# --- 单位与属性元数据 ---

# 湿空气计算中温度类的属性代码 (摄氏度 ↔ 开尔文)
TEMP_KEYS = {"T", "Tdb", "B", "Twb", "D", "Tdp"}
# 焓类属性代码 (kJ/kg ↔ J/kg)
ENTHALPY_KEYS = {"H", "Hda", "Hha"}

# 接口接受的所有有效已知状态参数代码（用于参数白名单校验）
VALID_INPUT_KEYS = {
    "P",     # 压力 (Pa)
    "T", "Tdb",   # 干球温度 (℃)
    "B", "Twb",   # 湿球温度 (℃)
    "D", "Tdp",   # 露点温度 (℃)
    "R",     # 相对湿度 (0 ~ 1)
    "W",     # 含湿量 (kg/kg 绝干气)
    "H", "Hda",   # 比焓 (kJ/kg 绝干气)
    "V", "Vda",   # 比容 (m^3/kg 绝干气)
    "S", "Sda",   # 比熵 (J/kg/K, 不做单位转换)
    "psi_w",  # 水蒸气摩尔分数
    "Y",      # 水蒸气摩尔分数
}


def convert_input(prop: str, val: float) -> float:
    """将用户提供的 ℃ / kJ·kg⁻¹ 输入转换为 CoolProp 需要的 SI 单位。"""
    if prop in TEMP_KEYS:
        return val + 273.15
    if prop in ENTHALPY_KEYS:
        return val * 1000.0
    return val


def convert_output(prop: str, val: float) -> float:
    """将 CoolProp 输出的 SI 单位转回 ℃ / kJ·kg⁻¹。"""
    if prop in TEMP_KEYS:
        return val - 273.15
    if prop in ENTHALPY_KEYS:
        return val / 1000.0
    return val


def _clean_error(err: Exception) -> str:
    """裁剪 CoolProp 异常信息（通常包含堆栈换行），只保留首行。"""
    return str(err).split("\n")[0][:300]


def _compute_one(out_prop: str, inputs: Dict[str, float]) -> float:
    """核心计算逻辑：接受输入字典（用户单位），返回用户单位的输出值。"""
    if len(inputs) != 3:
        raise ValueError(f"需要且仅需 3 个已知状态参数，当前提供了 {len(inputs)} 个")

    # 校验 key 合法性
    invalid = [k for k in inputs if k not in VALID_INPUT_KEYS]
    if invalid:
        raise ValueError(
            f"存在无效的属性代码: {invalid}。有效代码见 /haprops/keys"
        )

    # 校验数值有效性
    for k, v in inputs.items():
        if not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            raise ValueError(f"属性 {k} 的数值无效: {v}")

    # 单位转换并构建 CoolProp 调用参数
    args = []
    for k, v in inputs.items():
        args.extend([k, convert_input(k, float(v))])

    result_si = CP.HAPropsSI(out_prop, *args)
    return convert_output(out_prop, result_si)


# --- 自定义文档页面 CDN (解决默认 jsdelivr 在某些网络环境下不稳定) ---

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.9.0/swagger-ui-bundle.js",
        swagger_css_url="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.9.0/swagger-ui.css",
    )


@app.get("/redoc", include_in_schema=False)
async def redoc_html():
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=app.title + " - ReDoc",
        redoc_js_url="https://cdnjs.cloudflare.com/ajax/libs/redoc/2.0.0-rc.77/redoc.standalone.js",
    )


# --- 业务接口 ---

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get(
    "/haprops",
    summary="计算单点湿空气物性",
    description="根据 3 个已知状态参数计算湿空气的目标物性。参数名直接使用属性代码，例如 ?out_prop=H&P=101325&T=25&R=0.5",
    tags=["HumidAir"],
)
async def calculate_humid_air_properties(
    request: Request,
    out_prop: str = Query(..., description="输出属性代码，例如 H (焓)、W (含湿量)、Twb (湿球温度)"),
):
    query_params = dict(request.query_params)
    query_params.pop("out_prop", None)

    inputs: Dict[str, float] = {}
    for key, value in query_params.items():
        try:
            inputs[key] = float(value)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"参数 {key} 的值 '{value}' 不是有效的数字",
            )

    try:
        value = _compute_one(out_prop, inputs)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=_clean_error(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算错误: {_clean_error(e)}")

    return {
        "requested_property": out_prop,
        "inputs": inputs,
        "value": value,
        "status": "success",
    }


class BatchPoint(BaseModel):
    """一个湿空气状态点所需的输入。"""
    inputs: Dict[str, float] = Field(
        ..., description="3 个已知状态属性及其数值，例如 {\"P\": 101325, \"T\": 25, \"R\": 0.5}"
    )


class BatchRequest(BaseModel):
    out_prop: str = Field(..., description="输出属性代码，例如 H")
    points: List[BatchPoint] = Field(..., description="多个状态点的输入列表")


@app.post(
    "/haprops/batch",
    summary="批量计算湿空气物性",
    description="一次传入多个状态点，便于绘制焓湿图等批量计算场景。",
    tags=["HumidAir"],
)
async def calculate_batch(req: BatchRequest) -> Dict[str, Any]:
    results = []
    for idx, point in enumerate(req.points):
        try:
            value = _compute_one(req.out_prop, point.inputs)
            results.append({"index": idx, "inputs": point.inputs, "value": value, "status": "success"})
        except Exception as e:
            results.append({
                "index": idx,
                "inputs": point.inputs,
                "error": _clean_error(e),
                "status": "error",
            })
    return {"requested_property": req.out_prop, "count": len(results), "results": results}


@app.get(
    "/haprops/keys",
    summary="查询所有受支持的属性代码及单位",
    tags=["HumidAir"],
)
async def list_keys():
    return {
        "input_keys": sorted(VALID_INPUT_KEYS),
        "temperature_keys_celsius": sorted(TEMP_KEYS),
        "enthalpy_keys_kj_per_kg": sorted(ENTHALPY_KEYS),
        "notes": [
            "温度类属性 (T/Tdb/B/Twb/D/Tdp) 输入和输出单位均为 ℃",
            "焓类属性 (H/Hda/Hha) 输入和输出单位均为 kJ/kg 绝干气",
            "压力 P 单位为 Pa",
            "相对湿度 R 取值范围 0 ~ 1",
            "含湿量 W 单位为 kg 水蒸气 / kg 绝干气",
        ],
    }


@app.get("/health", summary="健康检查", tags=["System"])
async def health_check():
    return {"status": "ok", "service": "CoolProp API", "version": app.version}
