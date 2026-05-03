from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import CoolProp.CoolProp as CP

app = FastAPI(
    title="湿空气物性计算 API",
    description="基于 Python FastAPI 和 CoolProp 的湿空气物性计算服务",
    version="1.0.0"
)

templates = Jinja2Templates(directory="templates")

# 单位转换辅助函数
def convert_input(prop: str, val: float) -> float:
    prop_upper = prop.upper()
    if prop_upper in ["T", "TW", "TWB", "TDP", "TD"]:
        return val + 273.15  # ℃ -> K
    elif prop_upper in ["H", "HDA"]:
        return val * 1000.0  # kJ/kg -> J/kg
    return val

def convert_output(prop: str, val: float) -> float:
    prop_upper = prop.upper()
    if prop_upper in ["T", "TW", "TWB", "TDP", "TD"]:
        return val - 273.15  # K -> ℃
    elif prop_upper in ["H", "HDA"]:
        return val / 1000.0  # J/kg -> kJ/kg
    return val

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/haprops", summary="计算湿空气物性", description="基于给定的三个已知状态参数计算湿空气的目标物性")
async def calculate_humid_air_properties(
    request: Request,
    out_prop: str = Query(..., description="输出属性代码, 例如: H (焓), T (干球温度), R (相对湿度), W (含湿量)")
):
    # 获取所有的查询参数
    query_params = dict(request.query_params)
    
    # 移除出 out_prop 参数
    if "out_prop" in query_params:
        del query_params["out_prop"]
        
    # 提取已知属性参数 (排除 FastAPI 可能注入的其他内部参数)
    input_props = []
    for key, value in query_params.items():
        try:
            val_float = float(value)
            input_props.append((key, val_float))
        except ValueError:
            pass # 忽略无法转换为数字的参数

    if len(input_props) != 3:
        raise HTTPException(
            status_code=400, 
            detail=f"需要提供且仅提供 3 个有效的已知状态参数，目前提供了 {len(input_props)} 个: {[p[0] for p in input_props]}"
        )

    try:
        # 解包 3 个参数
        (p1, v1), (p2, v2), (p3, v3) = input_props

        # 单位转换: ℃ -> K, kJ/kg -> J/kg
        val1_si = convert_input(p1, v1)
        val2_si = convert_input(p2, v2)
        val3_si = convert_input(p3, v3)

        # 调用 CoolProp 的 HAPropsSI 函数
        result_si = CP.HAPropsSI(out_prop, p1, val1_si, p2, val2_si, p3, val3_si)
        
        # 单位转换: K -> ℃, J/kg -> kJ/kg
        result = convert_output(out_prop, result_si)

        return {
            "requested_property": out_prop,
            "inputs": {p1: v1, p2: v2, p3: v3},
            "value": result,
            "status": "success"
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=f"CoolProp 参数错误: {str(ve)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算过程中发生错误: {str(e)}")

# 简单健康检查接口
@app.get("/health", summary="健康检查", tags=["System"])
async def health_check():
    return {"status": "ok", "service": "CoolProp API"}
