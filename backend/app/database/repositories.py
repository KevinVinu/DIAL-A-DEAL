from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.models import Customer, Lead, Call, Conversation, Product, FollowUp
from app.database.schemas import (
    CustomerCreate, CustomerUpdate,
    LeadCreate, LeadUpdate,
    ProductCreate, ProductUpdate,
    FollowUpCreate
)

class CustomerRepository:
    @staticmethod
    def get_by_id(db: Session, customer_id: str) -> Optional[Customer]:
        return db.query(Customer).filter(Customer.id == customer_id).first()

    @staticmethod
    def get_by_phone(db: Session, phone_number: str) -> Optional[Customer]:
        return db.query(Customer).filter(Customer.phone_number == phone_number).first()

    @staticmethod
    def get_by_email(db: Session, email: str) -> Optional[Customer]:
        return db.query(Customer).filter(Customer.email == email).first()

    @staticmethod
    def get_or_create_anonymous(db: Session, preferred_language: str = "en-IN") -> Customer:
        customer = Customer(
            full_name="Website Prospect",
            preferred_language=preferred_language
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)
        return customer

    @staticmethod
    def create(db: Session, customer_in: CustomerCreate) -> Customer:
        customer = Customer(**customer_in.model_dump(exclude_unset=True))
        db.add(customer)
        db.commit()
        db.refresh(customer)
        return customer

    @staticmethod
    def update(db: Session, customer_id: str, customer_in: CustomerUpdate) -> Optional[Customer]:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            return None
        for field, value in customer_in.model_dump(exclude_unset=True).items():
            setattr(customer, field, value)
        customer.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(customer)
        return customer

    @staticmethod
    def list_all(db: Session, skip: int = 0, limit: int = 100) -> List[Customer]:
        return db.query(Customer).offset(skip).limit(limit).all()


class LeadRepository:
    @staticmethod
    def create(db: Session, lead_in: LeadCreate) -> Lead:
        lead = Lead(**lead_in.model_dump())
        db.add(lead)
        db.commit()
        db.refresh(lead)
        return lead

    @staticmethod
    def get_by_id(db: Session, lead_id: str) -> Optional[Lead]:
        return db.query(Lead).filter(Lead.id == lead_id).first()

    @staticmethod
    def update(db: Session, lead_id: str, lead_in: LeadUpdate) -> Optional[Lead]:
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return None
        for field, value in lead_in.model_dump(exclude_unset=True).items():
            setattr(lead, field, value)
        lead.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(lead)
        return lead

    @staticmethod
    def list_all(db: Session, skip: int = 0, limit: int = 100) -> List[Lead]:
        return db.query(Lead).offset(skip).limit(limit).all()


class CallRepository:
    @staticmethod
    def create_call(db: Session, call_session_id: str, customer_id: Optional[str], lead_id: Optional[str], language: str = "en-IN") -> Call:
        call = Call(
            call_session_id=call_session_id,
            customer_id=customer_id,
            lead_id=lead_id,
            language=language,
            call_status="In Progress",
            started_at=datetime.utcnow()
        )
        db.add(call)
        db.commit()
        db.refresh(call)
        return call

    @staticmethod
    def get_by_id(db: Session, call_id: str) -> Optional[Call]:
        return db.query(Call).filter(Call.id == call_id).first()

    @staticmethod
    def get_by_session_id(db: Session, session_id: str) -> Optional[Call]:
        return db.query(Call).filter(Call.call_session_id == session_id).first()

    @staticmethod
    def end_call(db: Session, call_id: str, outcome: Optional[str] = None, summary: Optional[str] = None, extracted_data: Optional[dict] = None) -> Optional[Call]:
        call = db.query(Call).filter(Call.id == call_id).first()
        if not call:
            return None
        now = datetime.utcnow()
        call.ended_at = now
        call.duration = (now - call.started_at).total_seconds()
        call.call_status = "Completed"
        if outcome:
            call.call_outcome = outcome
        if summary:
            call.summary = summary
        if extracted_data:
            call.extracted_data = extracted_data
        db.commit()
        db.refresh(call)
        return call

    @staticmethod
    def add_message(db: Session, call_id: str, speaker: str, message: str, language: str = "en-IN") -> Conversation:
        conv = Conversation(
            call_id=call_id,
            speaker=speaker,
            message=message,
            language=language,
            timestamp=datetime.utcnow()
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)
        return conv

    @staticmethod
    def get_transcript(db: Session, call_id: str) -> List[Conversation]:
        return db.query(Conversation).filter(Conversation.call_id == call_id).order_by(Conversation.timestamp.asc()).all()

    @staticmethod
    def list_all(db: Session, skip: int = 0, limit: int = 100) -> List[Call]:
        return db.query(Call).order_by(Call.started_at.desc()).offset(skip).limit(limit).all()


class ProductRepository:
    @staticmethod
    def create(db: Session, product_in: ProductCreate) -> Product:
        product = Product(**product_in.model_dump())
        db.add(product)
        db.commit()
        db.refresh(product)
        return product

    @staticmethod
    def get_by_id(db: Session, product_id: str) -> Optional[Product]:
        return db.query(Product).filter(Product.id == product_id).first()

    @staticmethod
    def update(db: Session, product_id: str, product_in: ProductUpdate) -> Optional[Product]:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return None
        for field, value in product_in.model_dump(exclude_unset=True).items():
            setattr(product, field, value)
        product.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(product)
        return product

    @staticmethod
    def list_all(db: Session, skip: int = 0, limit: int = 100) -> List[Product]:
        return db.query(Product).offset(skip).limit(limit).all()


class FollowUpRepository:
    @staticmethod
    def create(db: Session, follow_up_in: FollowUpCreate) -> FollowUp:
        follow_up = FollowUp(**follow_up_in.model_dump())
        db.add(follow_up)
        db.commit()
        db.refresh(follow_up)
        return follow_up

    @staticmethod
    def list_all(db: Session, skip: int = 0, limit: int = 100) -> List[FollowUp]:
        return db.query(FollowUp).order_by(FollowUp.follow_up_date.asc()).offset(skip).limit(limit).all()
