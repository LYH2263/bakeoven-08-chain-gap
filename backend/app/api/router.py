from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Batch, ChainGroup, ConflictLog, Oven, Product
from app.schemas.schemas import (
    BatchChainUpdate,
    BatchCreate,
    BatchOut,
    ChainGroupOut,
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


def _all_occupancies(db: Session) -> list[Occupancy]:
    batches = db.scalars(select(Batch)).all()
    out: list[Occupancy] = []
    for b in batches:
        p = db.get(Product, b.product_id)
        if not p:
            continue
        out.extend(build_occupancies(b.oven_id, b.id, b.start_min, _recipe(p)))
    return out


def _chain_member(db: Session, b: Batch) -> ChainMember:
    p = db.get(Product, b.product_id)
    o = db.get(Oven, b.oven_id)
    total = p.ferment_min + p.bake_min if p else 0
    return ChainMember(
        batch_id=b.id,
        code=b.code,
        oven_id=b.oven_id,
        oven_label=o.label if o else f"#{b.oven_id}",
        start_min=b.start_min,
        end_min=b.start_min + total,
    )


def _group_members(db: Session, group_id: int, exclude_id: int | None = None) -> list[ChainMember]:
    rows = db.scalars(select(Batch).where(Batch.chain_group_id == group_id)).all()
    return [_chain_member(db, b) for b in rows if b.id != exclude_id]


def _reject(db: Session, code: str, oven_id: int, detail: str):
    """Log the conflict and refuse the change: nothing else is committed."""
    db.add(ConflictLog(batch_code=code, oven_id=oven_id, detail=detail))
    db.commit()
    raise HTTPException(409, detail)


def _get_group(db: Session, name: str) -> ChainGroup | None:
    return db.scalar(select(ChainGroup).where(ChainGroup.name == name))


def _batch_out(db: Session, b: Batch) -> BatchOut:
    p = db.get(Product, b.product_id)
    o = db.get(Oven, b.oven_id)
    ferment_end = b.start_min + (p.ferment_min if p else 0)
    bake_end = ferment_end + (p.bake_min if p else 0)
    g = b.chain_group
    return BatchOut(
        id=b.id,
        product_id=b.product_id,
        oven_id=b.oven_id,
        code=b.code,
        start_min=b.start_min,
        status=b.status,
        product_name=p.name if p else None,
        oven_label=o.label if o else None,
        ferment_end=ferment_end,
        bake_end=bake_end,
        chain_group_id=b.chain_group_id,
        chain_group=g.name if g else None,
        chain_max_gap_min=g.max_gap_min if g else None,
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

    group_name = (body.chain_group or "").strip()
    group: ChainGroup | None = None
    gap = 0
    member_ids: set[int] = set()
    if group_name:
        group = _get_group(db, group_name)
        gap = (
            body.chain_max_gap_min
            if body.chain_max_gap_min is not None
            else (group.max_gap_min if group else 0)
        )
        members = _group_members(db, group.id) if group else []
        members.append(
            ChainMember(-1, code, oven.id, oven.label, body.start_min, body.start_min + recipe.total)
        )
        detail = validate_chain_group(members, gap, group_name)
        if detail:
            _reject(db, code, oven.id, detail)
        member_ids = {m.batch_id for m in members} - {-1}

    candidates = build_occupancies(oven.id, -1, body.start_min, recipe)
    existing = [o for o in _all_occupancies(db) if o.batch_id not in member_ids]
    hits = find_conflicts(existing, candidates)
    if hits:
        ex, cand = hits[0]
        detail = (
            f"与批次#{ex.batch_id} 的 {ex.phase} 段重叠："
            f"[{cand.interval.start},{cand.interval.end})"
        )
        _reject(db, code, oven.id, detail)

    if group_name:
        if group is None:
            group = ChainGroup(name=group_name, max_gap_min=gap)
            db.add(group)
            db.flush()
        else:
            group.max_gap_min = gap
    batch = Batch(
        product_id=product.id,
        oven_id=oven.id,
        code=code,
        start_min=body.start_min,
        chain_group_id=group.id if group else None,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return _batch_out(db, batch)


@api_router.patch("/batches/{batch_id}", response_model=BatchOut)
def update_batch_chain(batch_id: int, body: BatchChainUpdate, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(404, "批次不存在")
    fields = body.model_fields_set
    if not fields:
        return _batch_out(db, batch)

    old_group = batch.chain_group
    if "chain_group" in fields:
        name = (body.chain_group or "").strip()
    else:
        name = old_group.name if old_group else ""
    gap_provided = "chain_max_gap_min" in fields and body.chain_max_gap_min is not None
    if gap_provided and not name:
        raise HTTPException(400, "批次未指定连烤组，无法登记最大空档")

    target = _get_group(db, name) if name else None
    gap = 0
    if name:
        gap = (
            body.chain_max_gap_min
            if gap_provided
            else (target.max_gap_min if target else 0)
        )
        members = _group_members(db, target.id, exclude_id=batch.id) if target else []
        members.append(_chain_member(db, batch))
        detail = validate_chain_group(members, gap, name)
        if detail:
            _reject(db, batch.code, batch.oven_id, detail)
    if old_group and (target is None or old_group.id != target.id):
        remaining = _group_members(db, old_group.id, exclude_id=batch.id)
        detail = validate_chain_group(remaining, old_group.max_gap_min, old_group.name)
        if detail:
            _reject(db, batch.code, batch.oven_id, detail)

    if name:
        if target is None:
            target = ChainGroup(name=name, max_gap_min=gap)
            db.add(target)
            db.flush()
        elif gap_provided:
            target.max_gap_min = gap
        batch.chain_group_id = target.id
    elif "chain_group" in fields:
        batch.chain_group_id = None
    db.commit()
    db.refresh(batch)
    return _batch_out(db, batch)


@api_router.get("/chain-groups", response_model=list[ChainGroupOut])
def chain_groups(db: Session = Depends(get_db)):
    out: list[ChainGroupOut] = []
    for g in db.scalars(select(ChainGroup).order_by(ChainGroup.id)).all():
        codes = db.scalars(
            select(Batch.code).where(Batch.chain_group_id == g.id).order_by(Batch.start_min)
        ).all()
        out.append(
            ChainGroupOut(id=g.id, name=g.name, max_gap_min=g.max_gap_min, member_codes=list(codes))
        )
    return out


@api_router.get("/gantt", response_model=list[GanttBlock])
def gantt(db: Session = Depends(get_db)):
    blocks: list[GanttBlock] = []
    for b in db.scalars(select(Batch).order_by(Batch.start_min)).all():
        p = db.get(Product, b.product_id)
        o = db.get(Oven, b.oven_id)
        if not p or not o:
            continue
        group_name = b.chain_group.name if b.chain_group else None
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
                    chain_group=group_name,
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
