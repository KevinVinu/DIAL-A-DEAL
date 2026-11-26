from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.database.schemas import LeadCreate, LeadUpdate, LeadResponse
from app.database.repositories import LeadRepository

router = APIRouter(prefix="/api/leads", tags=["Leads"])

@router.get("", response_model=List[LeadResponse])
def list_leads(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return LeadRepository.list_all(db, skip=skip, limit=limit)

@router.post("", response_model=LeadResponse)
def create_lead(lead_in: LeadCreate, db: Session = Depends(get_db)):
    return LeadRepository.create(db, lead_in)

@router.get("/{lead_id}", response_model=LeadResponse)
def get_lead(lead_id: str, db: Session = Depends(get_db)):
    lead = LeadRepository.get_by_id(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead

@router.put("/{lead_id}", response_model=LeadResponse)
def update_lead(lead_id: str, lead_in: LeadUpdate, db: Session = Depends(get_db)):
    lead = LeadRepository.update(db, lead_id, lead_in)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead
