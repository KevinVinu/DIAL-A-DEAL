import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Text, DateTime, Float, ForeignKey, Integer, Boolean, JSON
)
from sqlalchemy.orm import relationship
from app.database.connection import Base

def generate_uuid():
    return str(uuid.uuid4())

class Customer(Base):
    __tablename__ = "customers"

    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    full_name = Column(String, nullable=True, index=True)
    age = Column(Integer, nullable=True)
    company = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    phone_number = Column(String, nullable=True, unique=True, index=True)
    email = Column(String, nullable=True, unique=True, index=True)
    preferred_language = Column(String, default="en-IN")
    location = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    leads = relationship("Lead", back_populates="customer", cascade="all, delete-orphan")
    calls = relationship("Call", back_populates="customer")
    follow_ups = relationship("FollowUp", back_populates="customer")
    meetings = relationship("Meeting", back_populates="customer")


class Lead(Base):
    __tablename__ = "leads"

    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False, index=True)
    source = Column(String, default="Website Call")
    lead_status = Column(String, default="New")  # New, Contacted, Qualified, Disqualified, Won, Lost
    interest_level = Column(String, default="Warm")  # Hot, Warm, Cold
    interested_products = Column(String, nullable=True)
    budget = Column(String, nullable=True)
    purchase_intent = Column(String, nullable=True)  # High, Medium, Low
    follow_up_required = Column(Boolean, default=False)
    follow_up_date = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    requirements = Column(Text, nullable=True)
    product_interest = Column(String, nullable=True)
    qualification_score = Column(Integer, default=0)   # 0-100
    conversation_summary = Column(Text, nullable=True)
    meeting_status = Column(String, default="None")    # None, Suggested, Pending, Scheduled, Cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = relationship("Customer", back_populates="leads")
    calls = relationship("Call", back_populates="lead")
    follow_ups = relationship("FollowUp", back_populates="lead")


class Call(Base):
    __tablename__ = "calls"

    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=True, index=True)
    lead_id = Column(String, ForeignKey("leads.id"), nullable=True, index=True)
    call_session_id = Column(String, unique=True, index=True)
    language = Column(String, default="en-IN")
    call_status = Column(String, default="In Progress")  # Connecting, In Progress, Completed, Interrupted, Failed
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    duration = Column(Float, default=0.0)  # in seconds
    call_outcome = Column(String, nullable=True)  # Qualified, Demo Booked, Callback, Not Interested
    summary = Column(Text, nullable=True)
    extracted_data = Column(JSON, nullable=True)  # BANT, requirements, objections, sentiment

    customer = relationship("Customer", back_populates="calls")
    lead = relationship("Lead", back_populates="calls")
    conversations = relationship("Conversation", back_populates="call", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    call_id = Column(String, ForeignKey("calls.id"), nullable=False, index=True)
    speaker = Column(String, nullable=False)  # 'ai' or 'customer'
    message = Column(Text, nullable=False)
    language = Column(String, default="en-IN")
    timestamp = Column(DateTime, default=datetime.utcnow)

    call = relationship("Call", back_populates="conversations")


class Product(Base):
    __tablename__ = "products"

    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    product_name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    price = Column(String, nullable=True)
    category = Column(String, nullable=True)
    features = Column(JSON, nullable=True)
    availability = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FollowUp(Base):
    __tablename__ = "follow_ups"

    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False, index=True)
    lead_id = Column(String, ForeignKey("leads.id"), nullable=True, index=True)
    call_id = Column(String, ForeignKey("calls.id"), nullable=True, index=True)
    follow_up_date = Column(DateTime, nullable=False)
    status = Column(String, default="Pending")  # Pending, Completed, Cancelled
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="follow_ups")
    lead = relationship("Lead", back_populates="follow_ups")


class Meeting(Base):
    """A meeting between a customer and the Fortivex team (backed by a Google Calendar event once scheduled)."""
    __tablename__ = "meetings"

    meeting_id = Column(String, primary_key=True, default=generate_uuid, index=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False, index=True)
    lead_id = Column(String, ForeignKey("leads.id"), nullable=True, index=True)
    session_id = Column(String, nullable=True, index=True)
    calendar_event_id = Column(String, nullable=True, unique=True, index=True)
    meeting_date = Column(String, nullable=True)   # YYYY-MM-DD (local timezone)
    meeting_time = Column(String, nullable=True)   # HH:MM 24h (local timezone)
    timezone = Column(String, default="Asia/Kolkata")
    duration = Column(Integer, default=30)         # minutes
    purpose = Column(Text, nullable=True)
    meeting_status = Column(String, default="Pending")  # Pending, Scheduled, Failed, Cancelled
    meeting_link = Column(String, nullable=True)
    email_status = Column(String, default="not_sent")   # not_sent, sent, failed
    failure_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = relationship("Customer", back_populates="meetings")


class ConversationSession(Base):
    """Persisted LangGraph conversation state, keyed by call/session id (one row per customer conversation)."""
    __tablename__ = "conversation_sessions"

    conversation_id = Column(String, primary_key=True, default=generate_uuid, index=True)
    session_id = Column(String, unique=True, nullable=False, index=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=True, index=True)
    lead_id = Column(String, ForeignKey("leads.id"), nullable=True, index=True)
    conversation_history = Column(JSON, default=list)
    agent_state = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

