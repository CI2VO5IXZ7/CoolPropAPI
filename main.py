from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import CoolProp.CoolProp as CP

app = FastAPI(
    title="CoolProp API",
    description="基于 Python FastAPI 和 CoolProp 的流体物性计算服务",
    version="1.0.0"
)

templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/props", summary="计算流体物性", description="基于给定的两个已知状态参数计算目标物性")
async def calculate_properties(
    fluid: str = Query(..., description="流体名称, 例如: Water, R134a, Nitrogen"),
    out_prop: str = Query(..., description="输出属性代码, 例如: D, H, S, T, P"),
    in_prop1: str = Query(..., description="第一个已知属性代码, 例如: P"),
    in_val1: float = Query(..., description="第一个已知属性的值"),
    in_prop2: str = Query(..., description="第二个已知属性代码, 例如: T"),
    in_val2: float = Query(..., description="第二个已知属性的值")
):
    try:
        # 调用 CoolProp 的 PropsSI 函数
        result = CP.PropsSI(out_prop, in_prop1, in_val1, in_prop2, in_val2, fluid)
        return {
            "fluid": fluid,
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
