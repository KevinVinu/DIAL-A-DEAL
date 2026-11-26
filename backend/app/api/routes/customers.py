from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.database.schemas import CustomerCreate, CustomerUpdate, CustomerResponse
from app.database.repositories import CustomerRepository

router = APIRouter(prefix="/api/customers", tags=["Customers"])

@router.get("", response_model=List[CustomerResponse])
def list_customers(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return CustomerRepository.list_all(db, skip=skip, limit=limit)

@router.post("", response_model=CustomerResponse)
def create_customer(customer_in: CustomerCreate, db: Session = Depends(get_db)):
    if customer_in.phone_number:
        existing = CustomerRepository.get_by_phone(db, customer_in.phone_number)
        if existing:
            return existing
    return CustomerRepository.create(db, customer_in)

@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(customer_id: str, db: Session = Depends(get_db)):
    customer = CustomerRepository.get_by_id(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer

@router.put("/{customer_id}", response_model=CustomerResponse)
def update_customer(customer_id: str, customer_in: CustomerUpdate, db: Session = Depends(get_db)):
    customer = CustomerRepository.update(db, customer_id, customer_in)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer
