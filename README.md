# 湿空气物性计算 API (CoolPropAPI)

基于 **FastAPI** + **CoolProp** 构建的湿空气物性计算 HTTP 服务，专为焓湿图 (h-d chart) 计算场景设计。

## 特性

- ✅ 直观的调用方式，属性代码即查询参数名，例如 `?out_prop=H&P=101325&T=25&R=0.5`
- ✅ 工程常用单位自动换算：温度 **℃**、焓值 **kJ/kg**、相对湿度 0-1
- ✅ 支持批量计算接口，便于绘制焓湿图等场景
- ✅ 提供可交互的在线 Playground 页面
- ✅ 启用 CORS，可在前端页面直接调用
- ✅ 一键部署到 Zeabur

## 接口一览

| 方法 | 路径 | 说明 |
|:---:|:---|:---|
| GET  | `/`              | 中文使用说明主页 + 在线试用 |
| GET  | `/haprops`       | 单点湿空气物性计算 |
| POST | `/haprops/batch` | 批量计算（JSON Body） |
| GET  | `/haprops/keys`  | 查询支持的属性代码 |
| GET  | `/docs`, `/redoc`| Swagger / ReDoc 文档 |
| GET  | `/health`        | 健康检查 |

## 本地运行

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080
```

浏览器访问 <http://localhost:8080> 查看文档。

## 部署到 Zeabur

1. Fork 或导入本仓库到您的 GitHub 账号。
2. 登录 [Zeabur](https://zeabur.com/)，新建项目 → 部署 GitHub 仓库。
3. Zeabur 会自动读取 `zeabur.json` 与 `requirements.txt` 完成构建和启动。

## 调用示例

```bash
# 大气压 25℃ 相对湿度 50% 的湿空气比焓
curl "https://coolpropapi.zeabur.app/haprops?out_prop=H&P=101325&T=25&R=0.5"

# 批量计算
curl -X POST https://coolpropapi.zeabur.app/haprops/batch \
  -H "Content-Type: application/json" \
  -d '{"out_prop":"W","points":[{"inputs":{"P":101325,"T":25,"R":0.5}}]}'
```

## 属性代码与单位

详见 [`/haprops/keys`](https://coolpropapi.zeabur.app/haprops/keys) 或主页表格。

## 许可证

MIT
