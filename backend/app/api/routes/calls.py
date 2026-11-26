import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.database.schemas import CallStartRequest, CallEndRequest, CallResponse, ConversationMessage
from app.database.repositories import CallRepository, CustomerRepository, LeadRepository

router = APIRouter(prefix="/api/calls", tags=["Calls"])

@router.post("/start", response_model=CallResponse)
def start_call(req: CallStartRequest, db: Session = Depends(get_db)):
    """Initialize a new call session and prepare context."""
    session_id = f"call_{uuid.uuid4().hex[:12]}"
    
    # Associate or create customer
    customer = None
    if req.phone_number:
        customer = CustomerRepository.get_by_phone(db, req.phone_number)
    if not customer and req.customer_id:
        customer = CustomerRepository.get_by_id(db, req.customer_id)
    if not customer:
        customer = CustomerRepository.get_or_create_anonymous(db, preferred_language=req.language or "en-IN")
        if req.full_name:
            customer.full_name = req.full_name
            db.commit()

    call = CallRepository.create_call(
        db,
        call_session_id=session_id,
        customer_id=customer.id,
        lead_id=None,
        language=req.language or "en-IN"
    )
    return call

@router.post("/end", response_model=CallResponse)
def end_call(req: CallEndRequest, db: Session = Depends(get_db)):
    """End a call and store outcome."""
    call = CallRepository.end_call(db, call_id=req.call_id, outcome=req.call_outcome, summary=req.summary)
    if not call:
        raise HTTPException(status_code=404, detail="Call session not found")
    return call

@router.get("/{call_id}", response_model=CallResponse)
def get_call(call_id: str, db: Session = Depends(get_db)):
    """Retrieve call session details."""
    call = CallRepository.get_by_id(db, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call record not found")
    return call

@router.get("/{call_id}/transcript", response_model=List[ConversationMessage])
def get_call_transcript(call_id: str, db: Session = Depends(get_db)):
    """Retrieve full transcript of a specific call."""
    return CallRepository.get_transcript(db, call_id)

@router.get("", response_model=List[CallResponse])
def list_calls(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    """List recent calls."""
    return CallRepository.list_all(db, skip=skip, limit=limit)
