"""
REST API router for part prices management.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import get_db
from ..schemas import PartPriceInfo, PartPriceCreate, PartPriceUpdate

router = APIRouter(prefix="/prices", tags=["Part Prices"])


@router.get("")
def list_prices(db=Depends(get_db)):
    """List all part prices."""
    rows = db.list_all_part_prices()
    return {
        "items": [
            {
                "id": r["id"],
                "product_model": r["product_model"],
                "part_name": r["part_name"],
                "price": r["price"],
                "currency": r.get("currency", "USD"),
                "updated_at": str(r.get("updated_at", "")),
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/model/{product_model}")
def get_model_prices(product_model: str, db=Depends(get_db)):
    """Get all part prices for a specific product model."""
    prices = db.get_all_prices_for_model(product_model)
    if prices is None:
        return {"items": {}, "product_model": product_model}
    return {"items": prices, "product_model": product_model}


@router.post("", status_code=201)
def create_price(body: PartPriceCreate, db=Depends(get_db)):
    """Create or update a part price."""
    success = db.upsert_part_price(
        body.product_model, body.part_name, body.price, body.currency
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save part price")
    return {"ok": True}


@router.patch("/{price_id}")
def update_price(price_id: int, body: PartPriceUpdate, db=Depends(get_db)):
    """Update a part price by ID."""
    # For simplicity, we use upsert with the existing product_model/part_name as key
    rows = db.list_all_part_prices()
    target = next((r for r in rows if r["id"] == price_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Part price not found")

    product_model = body.product_model or target["product_model"]
    part_name = body.part_name or target["part_name"]
    price = body.price if body.price is not None else target["price"]
    currency = body.currency or target.get("currency", "USD")

    # Delete old entry and insert new one (since model/part name might have changed)
    db.delete_part_price(price_id)
    success = db.upsert_part_price(product_model, part_name, price, currency)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update part price")
    return {"ok": True}


@router.delete("/{price_id}")
def delete_price(price_id: int, db=Depends(get_db)):
    """Delete a part price."""
    success = db.delete_part_price(price_id)
    if not success:
        raise HTTPException(status_code=404, detail="Part price not found")
    return {"ok": True}
