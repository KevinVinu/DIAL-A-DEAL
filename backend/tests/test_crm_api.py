import pytest
from fastapi.testclient import TestClient
from app.main import app

def test_health_check():
    with TestClient(app) as client:
        res = client.get("/")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "online"
        assert "DIAL-a-DEAL" in data["app"]

def test_start_and_end_call():
    with TestClient(app) as client:
        # Start call
        res = client.post("/api/calls/start", json={
            "phone_number": "+91 99999 88888",
            "full_name": "Test Prospect",
            "language": "en-IN",
            "scenario": "Enterprise SaaS Outbound"
        })
        assert res.status_code == 200
        call_data = res.json()
        assert "call_session_id" in call_data
        call_id = call_data["id"]

        # Get call details
        get_res = client.get(f"/api/calls/{call_id}")
        assert get_res.status_code == 200
        assert get_res.json()["id"] == call_id

        # End call
        end_res = client.post("/api/calls/end", json={
            "call_id": call_id,
            "call_outcome": "Demo Booked",
            "summary": "Customer interested in Enterprise tier."
        })
        assert end_res.status_code == 200
        assert end_res.json()["call_status"] == "Completed"

def test_customers_api():
    with TestClient(app) as client:
        # Create
        res = client.post("/api/customers", json={
            "full_name": "Arjun Test",
            "phone_number": "+91 98765 00001",
            "email": "arjun.test@example.com",
            "preferred_language": "en-IN"
        })
        assert res.status_code == 200
        customer_id = res.json()["id"]

        # List
        list_res = client.get("/api/customers")
        assert list_res.status_code == 200
        assert len(list_res.json()) >= 1

        # Get
        get_res = client.get(f"/api/customers/{customer_id}")
        assert get_res.status_code == 200
        assert get_res.json()["full_name"] == "Arjun Test"

def test_products_api():
    with TestClient(app) as client:
        res = client.get("/api/products")
        assert res.status_code == 200
        products = res.json()
        assert len(products) >= 1
        assert any("DIAL-a-DEAL" in p["product_name"] for p in products)

def test_leads_api():
    with TestClient(app) as client:
        # Create customer first
        c_res = client.post("/api/customers", json={
            "full_name": "Lead Test",
            "phone_number": "+91 88888 11111"
        })
        c_id = c_res.json()["id"]

        # Create lead
        l_res = client.post("/api/leads", json={
            "customer_id": c_id,
            "source": "Website Demo",
            "interest_level": "Hot",
            "budget": "₹8,00,000"
        })
        assert l_res.status_code == 200
        lead_id = l_res.json()["id"]

        # Update lead
        u_res = client.put(f"/api/leads/{lead_id}", json={
            "lead_status": "Qualified"
        })
        assert u_res.status_code == 200
        assert u_res.json()["lead_status"] == "Qualified"
