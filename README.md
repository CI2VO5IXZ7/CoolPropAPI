# CoolPropAPI

基于 **FastAPI** + **CoolProp** 的湿空气物性计算 HTTP 服务。给定任意 **2 个状态参数**，一次返回该状态点的全部湿空气物性，由调用方按需取用。压力 `P` 缺省 `101325 Pa`（标准大气压），可显式覆盖。另提供国标样式 **h-d 焓湿图**（PNG/SVG）。

在线地址：`http://<服务器IP>:18080`（完整使用文档直接访问服务主页 `/`）。

该地址是明文 HTTP，没有 TLS。请求与响应在链路上可见、也可被篡改，不要通过它传输密钥或其他秘密。需要加密时，在自有反向代理上终止 HTTPS，证书不要放进本仓库。

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
curl "http://<服务器IP>:18080/ha?T=25&R=0.5"

# 高原非标压
curl "http://<服务器IP>:18080/ha?T=25&R=0.5&P=80000"

# 批量
curl -X POST "http://<服务器IP>:18080/ha/batch" \
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
curl -o hd.png "http://<服务器IP>:18080/chart/hd"
curl -o hd.svg "http://<服务器IP>:18080/chart/hd?fmt=svg&points=25,0.5;30,0.6"
```

把 `<服务器IP>` 换成实际地址后，在浏览器打开即可预览：

`http://<服务器IP>:18080/chart/hd?width=900&points=25,0.5`

- 越界参数返回 400 JSON `{"detail": ...}`；成功响应带 `Cache-Control: public, max-age=86400`。
- 服务器缺少中文字体（Noto Sans CJK SC）时自动回退英文标签并记录 warning，不会 500；实际使用的语言见响应头 `Content-Language`。

## 校验与限流

- 输入越界返回 400：`P` 50000–110000 Pa；温度类（T/Tdb/B/Twb/D/Tdp）-100–200 ℃；`R` 0–1；`W` 0–0.1 kg/kg；`H`/`Hda` -100–500 kJ/kg。
- 同义参数（如 `T` 与 `Tdb`、`H` 与 `Hda`）同时出现返回 400。
- `/ha/batch` 单次最多 500 点，超过返回 400；单点错误仍按点返回 `status: "error"`。
- 限流（进程内存储）：每 IP 每分钟 60 次（各接口合计），`/chart/hd` 单独为每 IP 每分钟 10 次，超出返回 429；`/health` 不限流。默认限流键是 TCP 直连地址，伪造 `X-Forwarded-For` 不会换成新配额。仅当 `TRUST_PROXY=1`（信任 1 跳）或 `TRUST_PROXY_HOPS` 为大于等于 1 的整数时才读取该头。代理从左往右追加自己看到的对端，实现取从右数第 N 个地址（`TRUST_PROXY=1` 即最右侧，是最近一跳写入的对端）。`TRUST_PROXY_HOPS>=1` 优先于 `TRUST_PROXY`。地址个数少于 N、头不存在或拆出来是空的，仍用直连地址。不读取 `X-Real-IP`。这两个变量默认都不设置。
- CORS：`allow_origins=["*"]`，方法仅 GET / POST。

## 本地运行与测试

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/pytest -q
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080
```

访问 <http://localhost:8080> 查看文档。

主要依赖（`requirements.txt` 固定版本）：CoolProp 8.0.0、FastAPI 0.143.1、uvicorn 0.54.0、pydantic 2.14.1、Jinja2 3.1.6、slowapi 0.1.10、matplotlib 3.11.2、numpy 2.4.6。依赖由 Dependabot 每月检查更新。

## 自托管部署（上海）

镜像基于 `python:3.11-slim`，内置 `fonts-noto-cjk` 用于中文焓湿图。`.github/workflows/build.yml` 在推送到 `main` 或 `v*` 标签时，用 `GITHUB_TOKEN`（权限 `packages: write`）把镜像推到 `ghcr.io`。上海的机器不在本地编译，直接拉取全小写镜像。

```bash
docker compose pull
docker compose up -d
```

`docker-compose.yml` 使用 `ghcr.io/ci2vo5ixz7/coolpropapi:latest`，把容器内的 `8080` 映射到宿主机 `18080`，`restart: unless-stopped`，并带可选内存上限。镜像若为私有，先执行 `docker login ghcr.io`，凭据不要写入仓库。

默认不要设置 `TRUST_PROXY`。服务直接对客户端暴露时，限流按 TCP 直连地址。只有前面有你自己的反向代理、并且要按客户端地址限流时，才设置 `TRUST_PROXY=1`（取 `X-Forwarded-For` 最右侧那一格）。多级代理用 `TRUST_PROXY_HOPS`（大于等于 1 的整数，优先于 `TRUST_PROXY`，表示从右数第 N 格）。代理必须由你控制，并在转发时把真实对端追加到该头右侧。地址个数少于 N 时服务忽略该头。

明文 HTTP：对外地址是 `http://<服务器IP>:18080`。查询参数和响应在链路上可见，也可以被篡改；浏览器会把页面标为不安全，从 HTTPS 页面调用本接口会被混合内容策略拦截。不要用它传输密钥或其他秘密。公网若要加密，在前面的代理上终止 TLS，证书不要放进本仓库。

本地构建（不推远程）：

```bash
docker build -t coolpropapi:dev .
docker run --rm -p 18080:8080 coolpropapi:dev
```

## 许可证

[MIT](LICENSE)
