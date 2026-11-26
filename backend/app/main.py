from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database.connection import init_db, SessionLocal
from app.database.models import Product
from app.api.routes import calls, customers, leads, products, followups, chat, meetings
from app.api.websocket.voice_handler import VoiceWebSocketHandler
from app.rag.vector_store import ensure_index
from app.services.conversation_service import agent_service
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.PROJECT_NAME} v{settings.VERSION}")
    if not settings.SARVAM_API_KEY:
        logger.warning("[Config] SARVAM_API_KEY is not set — Sarvam Saaras V4 STT calls will return empty transcripts.")
    else:
        logger.info(f"[Config] STT configured: provider=sarvam model={settings.SARVAM_STT_MODEL} mode={settings.SARVAM_STT_MODE}")
    init_db()

    # Ensure ChromaDB RAG index is built from Fortivex verified knowledge base
    try:
        rag_report = ensure_index()
        logger.info(f"[RAG] Index ready: {rag_report.get('indexed')} records ({rag_report.get('status')})")
    except Exception as e:
        logger.error(f"[RAG] Failed to initialize vector index: {e}")

    # Seed initial products if database is empty (verified Fortivex products)
    db = SessionLocal()
    try:
        if db.query(Product).count() == 0:
            db.add_all([
                Product(
                    product_name="Fortivex CRM",
                    description="Admissions and student-lifecycle CRM for educational institutes and education businesses.",
                    price="₹999/user/month (Starter) · ₹1,999/user/month (Growth) · Custom (Enterprise)",
                    category="CRM",
                    features=["Lead capture & deduplication", "WhatsApp & AI chatbot qualification", "Student lifecycle", "Workflow automation"]
                ),
                Product(
                    product_name="Fortivex Attendance Management System (FAMS)",
                    description="Financial & Attendance Management System for workforce, attendance, leave, payroll and HR operations.",
                    price="On request (quoted per organisation)",
                    category="HR & Attendance",
                    features=["Daily attendance register", "Leave management", "Attendance-linked payroll", "Role-based access"]
                )
            ])
            db.commit()
            logger.info("[DB] Default Fortivex products seeded successfully.")
    finally:
        db.close()

    yield

    await agent_service.close()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Backend API, LangGraph Agentic RAG, and WebSocket real-time voice pipeline for DIAL-a-DEAL AI.",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include REST Routers
app.include_router(calls.router)
app.include_router(customers.router)
app.include_router(leads.router)
app.include_router(products.router)
app.include_router(followups.router)
app.include_router(chat.router)
app.include_router(meetings.router)

# WebSocket Real-Time Voice Endpoint
ws_voice_handler = VoiceWebSocketHandler()


@app.websocket("/ws/call/{call_session_id}")
async def websocket_call_endpoint(websocket: WebSocket, call_session_id: str):
    await ws_voice_handler.handle_call(websocket, call_session_id)


@app.get("/")
@app.get("/health")
def health_check():
    return {
        "status": "online",
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "supported_languages": list(settings.SUPPORTED_LANGUAGES.keys())
    }
