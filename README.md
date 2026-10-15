# CoolPropAPI

基于 **FastAPI** + **CoolProp** 的湿空气物性计算 HTTP 服务。给定任意 **2 个状态参数**，一次返回该状态点的全部湿空气物性，由调用方按需取用。压力 `P` 缺省 `101325 Pa`（标准大气压），可显式覆盖。另提供国标样式 **h-d 焓湿图**（PNG/SVG）。

在线地址：<https://coolpropapi.zeabur.app>（完整使用文档直接访问服务主页 `/`）

## 接口

| 方法 | 路径 | 说明 |
|:---:|:---|:---|
| GET  | `/`         | 使用文档主页 |
| GET  | `/ha`       | 单点全量物性计算 |
| POST | `/ha/batch` | 批量全量物性计算（最多 500 点） |
| GET  | `/ha/keys`  | 支持的属性代码与单位 |
| GET  | `/chart/hd` | 国标样式 h-d 焓湿图（PNG / SVG） |
| GET  | `/health`   | 健康检查 |

## 快速调用

```bash
# 标准大气，25 ℃，50% 相对湿度，全量物性
curl "https://coolpropapi.zeabur.app/ha?T=25&R=0.5"

# 高原非标压
curl "https://coolpropapi.zeabur.app/ha?T=25&R=0.5&P=80000"

# 批量
curl -X POST https://coolpropapi.zeabur.app/ha/batch \
  -H "Content-Type: application/json" \
  -d '{"points":[{"T":25,"R":0.5},{"T":30,"R":0.6}]}'
```

## 焓湿图 `GET /chart/hd`

斜角坐标 h-d 图：横轴为含湿量 d (g/kg 干空气)，画布纵坐标 `y = h − 2.5·d`，使等温线近似水平、等焓线向右下斜交（约 135°），与国内暖通教材插图同型。线族：等温线（每 1 ℃，每 10 ℃ 加粗）、等相对湿度线（10%–100%，饱和线加粗）、等焓线（每 10 kJ/kg）、等含湿量线。数值全部来自 CoolProp `HAPropsSI`，与 `/ha` 同源。

| 参数 | 默认 | 范围 | 说明 |
|---|---|---|---|
| `p` | 101325 | 50000–110000 Pa | 总压 |
| `t_min` / `t_max` | -10 / 45 | -30 ≤ t_min < t_max ≤ 60 ℃，跨度 ≥ 10 | 温度范围 |
| `d_max` | 30 | 5–60 g/kg | 横轴上限 |
| `fmt` | png | png \| svg | 输出格式 |
| `width` | 1200 | 600–2400 px | PNG 宽度，高度按比例 |
| `points` | — | ≤ 10 个，`T,R;T,R`（℃, 0–1） | 在图上标注状态点 |
| `lang` | zh | zh \| en | 标签语言 |

```bash
curl -o hd.png "https://coolpropapi.zeabur.app/chart/hd"
curl -o hd.svg "https://coolpropapi.zeabur.app/chart/hd?fmt=svg&points=25,0.5;30,0.6"
```

预览：

![h-d 焓湿图](https://coolpropapi.zeabur.app/chart/hd?width=900&points=25,0.5)

- 越界参数返回 400 JSON `{"detail": ...}`；成功响应带 `Cache-Control: public, max-age=86400`。
- 服务器缺少中文字体（Noto Sans CJK SC）时自动回退英文标签并记录 warning，不会 500；实际使用的语言见响应头 `Content-Language`。

## 校验与限流

- 输入越界返回 400：`P` 50000–110000 Pa；温度类（T/Tdb/B/Twb/D/Tdp）-100–200 ℃；`R` 0–1；`W` 0–0.1 kg/kg；`H`/`Hda` -100–500 kJ/kg。
- 同义参数（如 `T` 与 `Tdb`、`H` 与 `Hda`）同时出现返回 400。
- `/ha/batch` 单次最多 500 点，超过返回 400；单点错误仍按点返回 `status: "error"`。
- 限流（进程内存储）：每 IP 每分钟 60 次（各接口合计），`/chart/hd` 单独为每 IP 每分钟 10 次，超出返回 429；`/health` 不限流。IP 优先取 `X-Forwarded-For` 首个地址。
- CORS：`allow_origins=["*"]`，方法仅 GET / POST。

## 本地运行与测试

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/pytest -q
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080
```

访问 <http://localhost:8080> 查看文档。

主要依赖（`requirements.txt` 固定版本）：CoolProp 8.0.0、FastAPI 0.143.1、uvicorn 0.54.0、pydantic 2.14.1、Jinja2 3.1.6、slowapi 0.1.10、matplotlib 3.11.2、numpy 2.5.4。依赖由 Dependabot 每月检查更新。

## Docker 部署

镜像基于 `python:3.11-slim`，内置 `fonts-noto-cjk` 用于中文焓湿图。CI 自动构建并推送至 GHCR：

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

仓库根目录已含 `zeabur.json`。在 Zeabur 中导入本仓库即可一键部署。若 Zeabur 未使用 Dockerfile 构建，运行环境可能没有中文字体，此时焓湿图自动使用英文标签。

## 许可证

[MIT](LICENSE)
