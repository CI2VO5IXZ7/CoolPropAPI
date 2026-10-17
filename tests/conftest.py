import os
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault("CHART_PREWARM", "0")
os.environ.setdefault("MPLBACKEND", "Agg")

from main import app, limiter  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    # 用例默认处于「不信任代理」；个别用例再自行打开 TRUST_PROXY。
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    monkeypatch.delenv("TRUST_PROXY_HOPS", raising=False)
    limiter.reset()
    with TestClient(app) as c:
        yield c
