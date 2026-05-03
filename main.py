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
    out_prop: str = Query(..., description="输出属性代码, 例如: H (焓), T (干球温度), R (相对湿度), W (含湿量)"),
    in_prop1: str = Query(..., description="已知属性1代码, 例如: P (压力, Pa)"),
    in_val1: float = Query(..., description="已知属性1的值"),
    in_prop2: str = Query(..., description="已知属性2代码, 例如: T (温度, ℃)"),
    in_val2: float = Query(..., description="已知属性2的值"),
    in_prop3: str = Query(..., description="已知属性3代码, 例如: R (相对湿度, 0~1)"),
    in_val3: float = Query(..., description="已知属性3的值")
):
    try:
        # 单位转换: ℃ -> K, kJ/kg -> J/kg
        val1_si = convert_input(in_prop1, in_val1)
        val2_si = convert_input(in_prop2, in_val2)
        val3_si = convert_input(in_prop3, in_val3)

        # 调用 CoolProp 的 HAPropsSI 函数
        result_si = CP.HAPropsSI(out_prop, in_prop1, val1_si, in_prop2, val2_si, in_prop3, val3_si)
        
        # 单位转换: K -> ℃, J/kg -> kJ/kg
        result = convert_output(out_prop, result_si)

        return {
            "requested_property": out_prop,
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
