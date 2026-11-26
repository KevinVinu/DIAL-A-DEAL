from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.database.schemas import FollowUpCreate, FollowUpResponse
from app.database.repositories import FollowUpRepository

router = APIRouter(prefix="/api/followups", tags=["FollowUps"])

@router.get("", response_model=List[FollowUpResponse])
def list_followups(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return FollowUpRepository.list_all(db, skip=skip, limit=limit)

@router.post("", response_model=FollowUpResponse)
def create_followup(follow_up_in: FollowUpCreate, db: Session = Depends(get_db)):
    return FollowUpRepository.create(db, follow_up_in)
