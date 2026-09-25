from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Batch, ChainGroup, ConflictLog, Oven, Product


def seed_if_empty(db: Session) -> None:
    if db.scalar(select(Product.id).limit(1)):
        return
    products = [
        Product(name="乡村欧包", ferment_min=40, bake_min=35),
        Product(name="黄油可颂", ferment_min=25, bake_min=20),
        Product(name="布朗尼", ferment_min=0, bake_min=30),
    ]
    ovens = [
        Oven(label="一层 1 号炉", capacity_note="盘炉"),
        Oven(label="一层 2 号炉", capacity_note="盘炉"),
        Oven(label="二层石板炉", capacity_note="石板"),
    ]
    # BO-0900 收炉 10:15，BO-1030 开工 10:30：同炉空档 15 分钟，组成连烤组 G1。
    chain_g1 = ChainGroup(name="G1", max_gap_min=15)
    db.add_all(products + ovens + [chain_g1])
    db.flush()
    db.add_all(
        [
            Batch(product_id=products[0].id, oven_id=ovens[0].id, code="BO-0900", start_min=9 * 60, status="scheduled", chain_group_id=chain_g1.id),
            Batch(product_id=products[1].id, oven_id=ovens[0].id, code="BO-1030", start_min=10 * 60 + 30, status="scheduled", chain_group_id=chain_g1.id),
            Batch(product_id=products[2].id, oven_id=ovens[1].id, code="BO-1000", start_min=10 * 60, status="scheduled"),
        ]
    )
    db.add(
        ConflictLog(
            batch_code="BO-试排",
            oven_id=ovens[0].id,
            detail="试算与 BO-0900 烘烤段重叠（半开区间检测）",
        )
    )
    db.commit()
