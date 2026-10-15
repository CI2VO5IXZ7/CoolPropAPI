FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/opt/mplconfig

# /chart/hd 中文标签所需字体（Noto Sans CJK SC）
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CoolProp / matplotlib / numpy 均有 manylinux wheel，slim 镜像无需额外编译工具链
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && python -c "import matplotlib.font_manager as fm; fm.findfont('Noto Sans CJK SC', fallback_to_default=False)"

COPY main.py chart.py ./
COPY templates/ ./templates/

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=3).status==200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
