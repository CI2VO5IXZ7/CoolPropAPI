import os
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

from main import app, limiter  # noqa: E402


@pytest.fixture
def client():
    limiter.reset()
    with TestClient(app) as c:
        yield c
