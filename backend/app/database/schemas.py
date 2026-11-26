from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

# --- Customer Schemas ---
class CustomerBase(BaseModel):
    full_name: Optional[str] = None
    age: Optional[int] = None
    company: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    preferred_language: Optional[str] = "en-IN"
    location: Optional[str] = None

class CustomerCreate(CustomerBase):
    pass

class CustomerUpdate(CustomerBase):
    pass

class CustomerResponse(CustomerBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Lead Schemas ---
class LeadBase(BaseModel):
    customer_id: str
    source: Optional[str] = "Website Call"
    lead_status: Optional[str] = "New"
    interest_level: Optional[str] = "Warm"
    interested_products: Optional[str] = None
    budget: Optional[str] = None
    purchase_intent: Optional[str] = None
    follow_up_required: Optional[bool] = False
    follow_up_date: Optional[datetime] = None
    notes: Optional[str] = None

class LeadCreate(LeadBase):
    pass

class LeadUpdate(BaseModel):
    lead_status: Optional[str] = None
    interest_level: Optional[str] = None
    interested_products: Optional[str] = None
    budget: Optional[str] = None
    purchase_intent: Optional[str] = None
    follow_up_required: Optional[bool] = None
    follow_up_date: Optional[datetime] = None
    notes: Optional[str] = None

class LeadResponse(LeadBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Call Schemas ---
class CallStartRequest(BaseModel):
    customer_id: Optional[str] = None
    phone_number: Optional[str] = None
    full_name: Optional[str] = None
    language: Optional[str] = "en-IN"
    scenario: Optional[str] = "Enterprise SaaS Outbound"

class CallEndRequest(BaseModel):
    call_id: str
    call_outcome: Optional[str] = None
    summary: Optional[str] = None

class CallResponse(BaseModel):
    id: str
    customer_id: Optional[str] = None
    lead_id: Optional[str] = None
    call_session_id: str
    language: str
    call_status: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration: float
    call_outcome: Optional[str] = None
    summary: Optional[str] = None
    extracted_data: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


# --- Conversation Schemas ---
class ConversationMessage(BaseModel):
    id: str
    call_id: str
    speaker: str
    message: str
    language: str
    timestamp: datetime

    class Config:
        from_attributes = True


# --- Product Schemas ---
class ProductBase(BaseModel):
    product_name: str
    description: Optional[str] = None
    price: Optional[str] = None
    category: Optional[str] = None
    features: Optional[List[str]] = None
    availability: Optional[bool] = True

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    product_name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[str] = None
    category: Optional[str] = None
    features: Optional[List[str]] = None
    availability: Optional[bool] = None

class ProductResponse(ProductBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- FollowUp Schemas ---
class FollowUpBase(BaseModel):
    customer_id: str
    lead_id: Optional[str] = None
    call_id: Optional[str] = None
    follow_up_date: datetime
    status: Optional[str] = "Pending"
    notes: Optional[str] = None

class FollowUpCreate(FollowUpBase):
    pass

class FollowUpResponse(FollowUpBase):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True


# --- Lead Extraction Schema ---
class ExtractedLeadData(BaseModel):
    caller_name: Optional[str] = None
    caller_age: Optional[int] = None
    caller_company: Optional[str] = None
    customer_requirements: List[str] = Field(default_factory=list)
    products_of_interest: List[str] = Field(default_factory=list)
    budget: Optional[str] = None
    purchase_intent: str = Field(description="High, Medium, or Low", default="Medium")
    objections: List[str] = Field(default_factory=list)
    customer_sentiment: str = Field(description="Positive, Neutral, or Negative", default="Neutral")
    callback_requested: bool = False
    lead_temperature: str = Field(description="Hot, Warm, or Cold", default="Warm")
    suggested_next_action: str = ""
    conversation_summary: str = ""
