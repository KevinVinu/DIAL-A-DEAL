from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.database.schemas import ProductCreate, ProductUpdate, ProductResponse
from app.database.repositories import ProductRepository

router = APIRouter(prefix="/api/products", tags=["Products"])

@router.get("", response_model=List[ProductResponse])
def list_products(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return ProductRepository.list_all(db, skip=skip, limit=limit)

@router.post("", response_model=ProductResponse)
def create_product(product_in: ProductCreate, db: Session = Depends(get_db)):
    return ProductRepository.create(db, product_in)

@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: str, db: Session = Depends(get_db)):
    product = ProductRepository.get_by_id(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@router.put("/{product_id}", response_model=ProductResponse)
def update_product(product_id: str, product_in: ProductUpdate, db: Session = Depends(get_db)):
    product = ProductRepository.update(db, product_id, product_in)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product
