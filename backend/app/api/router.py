from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Batch, ConflictLog, Oven, Product
from app.schemas.schemas import (
    BatchCreate,
    BatchOut,
    BatchUpdate,
    ConflictOut,
    GanttBlock,
    OvenOut,
    ProductOut,
    WindowOut,
)
from app.services.oven_engine import (
    ChainMember,
    Occupancy,
    RecipeDurations,
    build_occupancies,
    find_conflicts,
    next_free_window,
    validate_chain_group,
)

api_router = APIRouter()


def _recipe(p: Product) -> RecipeDurations:
    return RecipeDurations(p.ferment_min, p.bake_min)


def _normalize_group(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    return v or None


def _chain_member(b: Batch, p: Product, max_gap_min: int | None = None) -> ChainMember:
    recipe = _recipe(p)
    gap = max_gap_min if max_gap_min is not None else (b.chain_max_gap_min or 0)
    return ChainMember(
        batch_id=b.id,
        code=b.code,
        oven_id=b.oven_id,
        start_min=b.start_min,
        end_min=b.start_min + recipe.total,
        max_gap_min=gap,
    )


def _group_members(db: Session, group: str, exclude_id: int | None = None) -> list[ChainMember]:
    rows = db.scalars(select(Batch).where(Batch.chain_group == group)).all()
    out: list[ChainMember] = []
    for b in rows:
        if exclude_id is not None and b.id == exclude_id:
            continue
        p = db.get(Product, b.product_id)
        if not p:
            continue
        out.append(_chain_member(b, p))
    return out


def _all_occupancies(db: Session) -> list[Occupancy]:
    batches = db.scalars(select(Batch)).all()
    out: list[Occupancy] = []
    for b in batches:
        p = db.get(Product, b.product_id)
        if not p:
            continue
        out.extend(build_occupancies(b.oven_id, b.id, b.start_min, _recipe(p)))
    return out


def _batch_out(db: Session, b: Batch) -> BatchOut:
    p = db.get(Product, b.product_id)
    o = db.get(Oven, b.oven_id)
    ferment_end = b.start_min + (p.ferment_min if p else 0)
    bake_end = ferment_end + (p.bake_min if p else 0)
    return BatchOut(
        id=b.id,
        product_id=b.product_id,
        oven_id=b.oven_id,
        code=b.code,
        start_min=b.start_min,
        status=b.status,
        chain_group=b.chain_group,
        chain_max_gap_min=b.chain_max_gap_min,
        product_name=p.name if p else None,
        oven_label=o.label if o else None,
        ferment_end=ferment_end,
        bake_end=bake_end,
    )


@api_router.get("/health")
def health():
    return {"status": "ok"}


@api_router.get("/products", response_model=list[ProductOut])
def products(db: Session = Depends(get_db)):
    return db.scalars(select(Product).order_by(Product.id)).all()


@api_router.get("/ovens", response_model=list[OvenOut])
def ovens(db: Session = Depends(get_db)):
    return db.scalars(select(Oven).order_by(Oven.id)).all()


@api_router.get("/batches", response_model=list[BatchOut])
def batches(db: Session = Depends(get_db)):
    rows = db.scalars(select(Batch).order_by(Batch.start_min)).all()
    return [_batch_out(db, b) for b in rows]


@api_router.post("/batches", response_model=BatchOut)
def create_batch(body: BatchCreate, db: Session = Depends(get_db)):
    product = db.get(Product, body.product_id)
    oven = db.get(Oven, body.oven_id)
    if not product or not oven:
        raise HTTPException(404, "产品或炉位不存在")
    recipe = _recipe(product)
    code = body.code or f"BO-{body.start_min}"
    group = _normalize_group(body.chain_group)
    max_gap = body.chain_max_gap_min if group else None
    if group and max_gap is None:
        max_gap = 0
    if group:
        members = _group_members(db, group)
        members.append(
            ChainMember(0, code, oven.id, body.start_min, body.start_min + recipe.total, max_gap)
        )
        violation = validate_chain_group(group, members)
        if violation:
            db.add(ConflictLog(batch_code=code, oven_id=oven.id, detail=violation.detail))
            db.commit()
            raise HTTPException(409, violation.detail)
    candidates = build_occupancies(oven.id, -1, body.start_min, recipe)
    existing = _all_occupancies(db)
    hits = find_conflicts(existing, candidates)
    if hits:
        ex, cand = hits[0]
        detail = (
            f"与批次#{ex.batch_id} 的 {ex.phase} 段重叠："
            f"[{cand.interval.start},{cand.interval.end})"
        )
        db.add(ConflictLog(batch_code=code, oven_id=oven.id, detail=detail))
        db.commit()
        raise HTTPException(409, detail)
    batch = Batch(
        product_id=product.id,
        oven_id=oven.id,
        code=code,
        start_min=body.start_min,
        chain_group=group,
        chain_max_gap_min=max_gap,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return _batch_out(db, batch)


@api_router.patch("/batches/{batch_id}", response_model=BatchOut)
def update_batch(batch_id: int, body: BatchUpdate, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(404, "批次不存在")
    fields = body.model_fields_set
    old_group = batch.chain_group
    new_group = _normalize_group(body.chain_group) if "chain_group" in fields else old_group
    if "chain_max_gap_min" in fields:
        new_gap = body.chain_max_gap_min
    elif "chain_group" in fields and new_group != old_group:
        new_gap = None
    else:
        new_gap = batch.chain_max_gap_min
    if new_group is None:
        new_gap = None
    elif new_gap is None:
        new_gap = 0

    # The whole affected group(s) must stay valid after the edit, otherwise
    # the edit is rejected and nothing changes (no half group on the gantt).
    affected = {g for g in (old_group, new_group) if g}
    for group in sorted(affected):
        members = _group_members(db, group, exclude_id=batch.id)
        if new_group == group:
            p = db.get(Product, batch.product_id)
            if p:
                members.append(_chain_member(batch, p, max_gap_min=new_gap))
        violation = validate_chain_group(group, members)
        if violation:
            db.add(ConflictLog(batch_code=batch.code, oven_id=batch.oven_id, detail=violation.detail))
            db.commit()
            raise HTTPException(409, violation.detail)

    batch.chain_group = new_group
    batch.chain_max_gap_min = new_gap
    db.commit()
    db.refresh(batch)
    return _batch_out(db, batch)


@api_router.get("/gantt", response_model=list[GanttBlock])
def gantt(db: Session = Depends(get_db)):
    blocks: list[GanttBlock] = []
    for b in db.scalars(select(Batch).order_by(Batch.start_min)).all():
        p = db.get(Product, b.product_id)
        o = db.get(Oven, b.oven_id)
        if not p or not o:
            continue
        for occ in build_occupancies(b.oven_id, b.id, b.start_min, _recipe(p)):
            blocks.append(
                GanttBlock(
                    batch_id=b.id,
                    code=b.code,
                    oven_id=o.id,
                    oven_label=o.label,
                    phase=occ.phase,
                    start_min=occ.interval.start,
                    end_min=occ.interval.end,
                    chain_group=b.chain_group,
                )
            )
    return blocks


@api_router.get("/conflicts", response_model=list[ConflictOut])
def conflicts(db: Session = Depends(get_db)):
    return db.scalars(select(ConflictLog).order_by(ConflictLog.id.desc())).all()


@api_router.get("/windows", response_model=list[WindowOut])
def windows(product_id: int, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "产品不存在")
    duration = product.ferment_min + product.bake_min
    existing = _all_occupancies(db)
    out: list[WindowOut] = []
    for oven in db.scalars(select(Oven).order_by(Oven.id)).all():
        w = next_free_window(existing, oven.id, duration, search_from=8 * 60, search_to=22 * 60)
        if w:
            out.append(
                WindowOut(
                    oven_id=oven.id,
                    oven_label=oven.label,
                    start_min=w.start,
                    end_min=w.end,
                    duration_min=duration,
                )
            )
    return out
