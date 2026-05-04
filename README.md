# CoolPropAPI

基于 **FastAPI** + **CoolProp** 的湿空气物性计算 HTTP 服务。给定任意 **2 个状态参数**，一次返回该状态点的全部湿空气物性，由调用方按需取用。压力 `P` 缺省 `101325 Pa`（标准大气压），可显式覆盖。

完整使用文档直接访问服务主页 `/` 即可（无需 `/docs`）。

## 接口

| 方法 | 路径 | 说明 |
|:---:|:---|:---|
| GET  | `/`         | 使用文档主页 |
| GET  | `/ha`       | 单点全量物性计算 |
| POST | `/ha/batch` | 批量全量物性计算 |
| GET  | `/ha/keys`  | 支持的属性代码与单位 |
| GET  | `/health`   | 健康检查 |

## 快速调用

```bash
# 标准大气，25 ℃，50% 相对湿度，全量物性
curl "https://your-host/ha?T=25&R=0.5"

# 高原非标压
curl "https://your-host/ha?T=25&R=0.5&P=80000"

# 批量
curl -X POST https://your-host/ha/batch \
  -H "Content-Type: application/json" \
  -d '{"points":[{"T":25,"R":0.5},{"T":30,"R":0.6}]}'
```

## 本地运行

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080
```

访问 <http://localhost:8080> 查看文档。

## Docker 部署

CI 自动构建并推送至 GHCR：

```bash
docker run -d --name coolpropapi -p 8080:8080 \
  ghcr.io/ci2vo5ixz7/coolpropapi:latest
```

本地构建：

```bash
docker build -t coolpropapi:dev .
docker run --rm -p 8080:8080 coolpropapi:dev
```

## Zeabur 部署

仓库根目录已含 `zeabur.json`。在 Zeabur 中导入本仓库即可一键部署。

## 许可证

MIT
