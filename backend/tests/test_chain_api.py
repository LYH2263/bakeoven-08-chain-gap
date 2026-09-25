"""API-level tests for 同炉连烤 chain groups.

Runs against an in-memory SQLite app (no lifespan, no Postgres) with the
get_db dependency overridden.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.database import Base, get_db
from app.models.models import Oven, Product


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestingSession()
    # product 1 occupies 75 min, product 2 occupies 45 min
    db.add_all(
        [
            Product(name="欧包", ferment_min=40, bake_min=35),
            Product(name="可颂", ferment_min=25, bake_min=20),
            Oven(label="1号炉"),
            Oven(label="2号炉"),
        ]
    )
    db.commit()
    db.close()

    def override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c


def post(client, **kw):
    return client.post("/api/batches", json=kw)


def codes(client):
    return [b["code"] for b in client.get("/api/batches").json()]


def test_chain_group_created_and_persisted(client):
    r = post(client, product_id=1, oven_id=1, start_min=540, code="A1",
             chain_group="L1", chain_max_gap_min=20)
    assert r.status_code == 200, r.text
    assert r.json()["chain_group"] == "L1"
    assert r.json()["chain_max_gap_min"] == 20
    # A1 occupies 540..615; A2 at 625 -> gap 10 <= 20
    r = post(client, product_id=2, oven_id=1, start_min=625, code="A2",
             chain_group="L1", chain_max_gap_min=20)
    assert r.status_code == 200, r.text
    rows = client.get("/api/batches").json()
    assert [(b["code"], b["chain_group"], b["chain_max_gap_min"]) for b in rows] == [
        ("A1", "L1", 20),
        ("A2", "L1", 20),
    ]


def test_cross_oven_rejects_whole_group(client):
    assert post(client, product_id=1, oven_id=1, start_min=540, code="A1",
                chain_group="L1", chain_max_gap_min=20).status_code == 200
    r = post(client, product_id=2, oven_id=2, start_min=620, code="A2",
             chain_group="L1", chain_max_gap_min=20)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "跨炉" in detail and "A1" in detail and "A2" in detail
    # 整组拒绝：甘特/批次里不留半组
    assert codes(client) == ["A1"]
    logs = client.get("/api/conflicts").json()
    assert any("跨炉" in c["detail"] and "A1" in c["detail"] and "A2" in c["detail"]
               for c in logs)


def test_gap_exceeded_rejected(client):
    assert post(client, product_id=1, oven_id=1, start_min=540, code="A1",
                chain_group="L1", chain_max_gap_min=20).status_code == 200
    r = post(client, product_id=2, oven_id=1, start_min=640, code="A2",
             chain_group="L1", chain_max_gap_min=20)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "空档" in detail and "A1" in detail and "A2" in detail
    assert codes(client) == ["A1"]


def test_zero_gap_requires_exact_touch(client):
    assert post(client, product_id=1, oven_id=1, start_min=540, code="A1",
                chain_group="L1", chain_max_gap_min=0).status_code == 200
    # A1 ends 615; exact touch ok
    assert post(client, product_id=2, oven_id=1, start_min=615, code="A2",
                chain_group="L1", chain_max_gap_min=0).status_code == 200
    # A2 ends 660; one minute late is rejected
    r = post(client, product_id=2, oven_id=1, start_min=661, code="A3",
             chain_group="L1", chain_max_gap_min=0)
    assert r.status_code == 409
    assert "空档" in r.json()["detail"]
    assert post(client, product_id=2, oven_id=1, start_min=660, code="A3",
                chain_group="L1", chain_max_gap_min=0).status_code == 200


def test_group_without_gap_defaults_to_zero(client):
    r = post(client, product_id=1, oven_id=1, start_min=540, code="A1", chain_group="L1")
    assert r.status_code == 200 and r.json()["chain_max_gap_min"] == 0
    r = post(client, product_id=2, oven_id=1, start_min=616, code="A2", chain_group="L1")
    assert r.status_code == 409


def test_ungrouped_overlap_rule_unchanged(client):
    assert post(client, product_id=1, oven_id=1, start_min=540, code="B1").status_code == 200
    r = post(client, product_id=2, oven_id=1, start_min=550, code="B2")
    assert r.status_code == 409
    assert "重叠" in r.json()["detail"]
    assert post(client, product_id=2, oven_id=1, start_min=615, code="B2").status_code == 200


def test_grouped_batch_still_respects_other_occupancy(client):
    assert post(client, product_id=1, oven_id=1, start_min=540, code="B1").status_code == 200
    r = post(client, product_id=2, oven_id=1, start_min=600, code="A1",
             chain_group="L1", chain_max_gap_min=30)
    assert r.status_code == 409
    assert "重叠" in r.json()["detail"]


def test_patch_group_and_gap_persist(client):
    post(client, product_id=1, oven_id=1, start_min=540, code="A1")
    post(client, product_id=2, oven_id=1, start_min=620, code="A2")
    bid = client.get("/api/batches").json()[1]["id"]
    r = client.patch(f"/api/batches/{bid}", json={"chain_group": "L1", "chain_max_gap_min": 10})
    assert r.status_code == 200, r.text
    # 离开再进来仍在：重新 GET 仍是 L1/10
    rows = {b["code"]: b for b in client.get("/api/batches").json()}
    assert rows["A2"]["chain_group"] == "L1"
    assert rows["A2"]["chain_max_gap_min"] == 10
    # A1 joins the same group; gap 620-615=5 <= 10
    aid = rows["A1"]["id"]
    r = client.patch(f"/api/batches/{aid}", json={"chain_group": "L1", "chain_max_gap_min": 10})
    assert r.status_code == 200, r.text
    rows = {b["code"]: b for b in client.get("/api/batches").json()}
    assert rows["A1"]["chain_group"] == "L1"


def test_patch_shrinking_gap_below_existing_rejected(client):
    post(client, product_id=1, oven_id=1, start_min=540, code="A1",
         chain_group="L1", chain_max_gap_min=20)
    post(client, product_id=2, oven_id=1, start_min=625, code="A2",
         chain_group="L1", chain_max_gap_min=20)
    bid = client.get("/api/batches").json()[1]["id"]
    r = client.patch(f"/api/batches/{bid}", json={"chain_max_gap_min": 5})
    assert r.status_code == 409
    assert "空档" in r.json()["detail"]
    rows = {b["code"]: b for b in client.get("/api/batches").json()}
    assert rows["A2"]["chain_max_gap_min"] == 20  # unchanged


def test_leaving_group_that_breaks_chain_rejected(client):
    post(client, product_id=1, oven_id=1, start_min=540, code="A1",
         chain_group="L1", chain_max_gap_min=10)
    post(client, product_id=2, oven_id=1, start_min=615, code="A2",
         chain_group="L1", chain_max_gap_min=10)
    post(client, product_id=2, oven_id=1, start_min=665, code="A3",
         chain_group="L1", chain_max_gap_min=10)
    bid = {b["code"]: b["id"] for b in client.get("/api/batches").json()}["A2"]
    # removing A2 would leave A1(ends 615) and A3(starts 665) with gap 50 > 10
    r = client.patch(f"/api/batches/{bid}", json={"chain_group": None})
    assert r.status_code == 409
    rows = {b["code"]: b for b in client.get("/api/batches").json()}
    assert rows["A2"]["chain_group"] == "L1"


def test_gantt_marks_chain_group(client):
    post(client, product_id=1, oven_id=1, start_min=540, code="A1",
         chain_group="L1", chain_max_gap_min=20)
    post(client, product_id=2, oven_id=1, start_min=625, code="A2",
         chain_group="L1", chain_max_gap_min=20)
    post(client, product_id=2, oven_id=2, start_min=540, code="B1")
    blocks = client.get("/api/gantt").json()
    by_code = {}
    for blk in blocks:
        by_code.setdefault(blk["code"], set()).add(blk["chain_group"])
    assert by_code["A1"] == {"L1"}
    assert by_code["A2"] == {"L1"}
    assert by_code["B1"] == {None}
