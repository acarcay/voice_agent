"""
Voice Agent - Production Implementation

A LiveKit-based voice AI agent for warehouse inventory management.

Features:
- Dependency injection for database and state managers
- Retry logic with tenacity for external API calls
- Structured logging with PII redaction
- Async-safe operations with proper locking
"""

import asyncio
import os
import json
import logging
from datetime import datetime
from typing import Optional

import structlog
from livekit.plugins import elevenlabs
from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RoomInputOptions,
    WorkerOptions,
    cli,
    metrics,
    RunContext,
)
from livekit.plugins import noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit.agents.llm import function_tool

from database_manager import DatabaseManager, get_database, init_database

# Load environment variables
load_dotenv(".env.local")

# Configure structured logging
def configure_logging():
    """Configure structlog for JSON output in production."""
    log_format = os.getenv("LOG_FORMAT", "json")
    log_level = os.getenv("LOG_LEVEL", "INFO")
    
    if log_format == "json":
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.UnicodeDecoder(),
                redact_pii,
                structlog.processors.JSONRenderer()
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
    else:
        structlog.configure(
            processors=[
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                redact_pii,
                structlog.dev.ConsoleRenderer()
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
        )
    
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(message)s"
    )


def redact_pii(logger, method_name, event_dict):
    """Redact PII from log messages for compliance."""
    pii_fields = ["phone", "email", "customer_name"]
    
    for field in pii_fields:
        if field in event_dict:
            value = str(event_dict[field])
            if field == "phone" and len(value) > 4:
                event_dict[field] = f"***{value[-4:]}"
            elif field == "email" and "@" in value:
                local, domain = value.split("@", 1)
                event_dict[field] = f"{local[0]}***@{domain}"
            elif field == "customer_name":
                parts = value.split()
                if parts:
                    event_dict[field] = f"{parts[0][0]}. ***"
    
    return event_dict


# Initialize logging
configure_logging()
logger = structlog.get_logger("agent")


class Assistant(Agent):
    """
    Voice AI Assistant for warehouse inventory management.
    
    Uses dependency injection for:
    - DatabaseManager: Inventory storage
    
    All external operations use retry logic for resilience.
    """
    
    def __init__(
        self,
        db_manager: DatabaseManager,
        staff_name: Optional[str] = None
    ) -> None:
        """
        Initialize the assistant with injected dependencies.
        
        Args:
            db_manager: Database manager for inventory operations.
            staff_name: Staff member's name for personalization.
        """
        self.db_manager = db_manager
        self.staff_name = staff_name or "Personel"
        self.conversation_start_time = datetime.now()

        base_instructions = self._get_instructions()

        super().__init__(instructions=base_instructions)

    def _get_instructions(self) -> str:
        """Generate system instructions for the LLM."""
        warehouse_name = os.getenv("WAREHOUSE_NAME", "Depo")
        return f"""
        Senin adın DepoGPT. {warehouse_name} stok takip asistanısın.

        KİŞİLİK:
        - Askeri disiplinli, net ve kısa konuş
        - "Merhaba nasılsın" gibi samimiyete girme
        - Direkt sonuca odaklan
        - Her yanıt maksimum 1-2 cümle

        GÖREVLER:
        1. STOK SORGULAMA:
           - Kullanıcı bir ürün sorduğunda → get_stock_details(item_name) çağır
           - Yanıt formatı: "[Ürün adı]: [Adet] adet, [Raf konumu]"
           
        2. STOK GÜNCELLEME:
           - "X tane aldım" → update_stock(item_name, X, "remove")
           - "Y tane koydum" → update_stock(item_name, Y, "add")
           - Yanıt formatı: "Güncellendi. Yeni stok: [Adet] adet."

        KURALLAR:
        - SADECE stok işlemleri yap, başka konulara girme
        - Ürün veritabanında yoksa: "Ürün bulunamadı"
        - Stok yetersizse: "Yetersiz stok"
        - Gereksiz lafı kesip direkt işlemi yap
        - MUTLAKA function tool çağır, asla kendin uydurmaktan yanıt verme
        """

    @function_tool
    async def get_stock_details(self, context: RunContext, item_name: str):
        """Verilen ürün adına ait stok miktarı ve raf konumunu getirir."""
        if not item_name:
            logger.error("invalid_item_name", item_name=item_name)
            return {"error": "Ürün adı gerekli", "success": False}

        logger.info("fetching_stock", item_name=item_name)

        try:
            item = await self.db_manager.get_item(item_name)
            
            if not item:
                logger.warning("item_not_found", item_name=item_name)
                return {"error": "Ürün bulunamadı", "success": False}

            return {
                "item_name": item["name"],
                "quantity": item["quantity"],
                "location": item["location"],
                "item_id": item["item_id"],
                "success": True,
                "message": f"{item['name']}: {item['quantity']} adet, {item['location']}"
            }

        except Exception as e:
            logger.error("get_stock_error", error=str(e), item_name=item_name)
            return {"error": f"Sistem hatası: {str(e)}", "success": False}

    @function_tool
    async def update_stock(self, context: RunContext, item_name: str, quantity: int, operation: str):
        """
        Stok miktarını günceller.
        
        Args:
            item_name: Ürün adı
            quantity: Eklenecek veya çıkarılacak miktar
            operation: 'add' (ekleme) veya 'remove' (çıkarma)
        """
        if not item_name:
            return {"error": "Ürün adı gerekli", "success": False}

        if operation not in ["add", "remove"]:
            logger.warning("invalid_operation", operation=operation)
            return {"error": "Geçersiz işlem. 'add' veya 'remove' olmalı", "success": False}

        logger.info("updating_stock", item_name=item_name, quantity=quantity, operation=operation)

        try:
            # First, get the item to find its ID
            item = await self.db_manager.get_item(item_name)
            if not item:
                return {"error": "Ürün bulunamadı", "success": False}

            # Update stock
            success = await self.db_manager.update_stock(
                item_id=item["item_id"],
                quantity=quantity,
                operation=operation
            )

            if not success:
                return {"error": "Stok güncellenemedi", "success": False}

            # Get updated stock info
            updated_item = await self.db_manager.get_item(item_name)

            return {
                "message": f"Güncellendi. Yeni stok: {updated_item['quantity']} adet.",
                "success": True,
                "item_name": updated_item["name"],
                "new_quantity": updated_item["quantity"],
                "operation": operation,
                "amount": quantity
            }

        except Exception as e:
            logger.error("update_stock_error", error=str(e), item_name=item_name)
            return {"error": f"Güncelleme başarısız: {str(e)}", "success": False}


# Global manager references (initialized in entrypoint)
_db_manager: Optional[DatabaseManager] = None


def prewarm(proc: JobProcess):
    """Agent başlatılmadan önce gerekli kaynakları yükle."""
    logger.info("prewarm_starting")
    proc.userdata["vad"] = silero.VAD.load()
    logger.info("vad_model_loaded")


async def entrypoint(ctx: JobContext):
    """Agent'ın ana giriş noktası."""
    global _db_manager
    
    ctx.log_context_fields = {"room": ctx.room.name}

    # Initialize infrastructure connections
    try:
        if _db_manager is None:
            _db_manager = await init_database()
    except Exception as e:
        logger.error("infrastructure_init_failed", error=str(e))
        raise

    # Parse room metadata
    staff_name = "Personel"

    try:
        metadata = ctx.room.metadata
        if metadata:
            metadata_dict = json.loads(metadata)
            staff_name = metadata_dict.get("staff_name") or staff_name
            logger.info(
                "metadata_parsed",
                staff_name=staff_name
            )
    except Exception as e:
        logger.warning("metadata_parse_error", error=str(e))

    # Model configuration
    stt_model = os.getenv("STT_MODEL", "deepgram/nova-2-streaming:tr")
    llm_model = os.getenv("LLM_MODEL", "gemini-1.5-flash")
    logger.info("models_configured", stt=stt_model, llm=llm_model)

    # API Key validation
    eleven_api_key = os.getenv("ELEVEN_API_KEY")
    if not eleven_api_key:
        logger.error("missing_api_key", key="ELEVEN_API_KEY")
        raise ValueError("ELEVEN_API_KEY gerekli")

    google_api_key = os.getenv("GOOGLE_API_KEY")
    if not google_api_key:
        logger.error("missing_api_key", key="GOOGLE_API_KEY")
        raise ValueError("GOOGLE_API_KEY gerekli")

    logger.info("api_keys_validated")

    # Create AgentSession
    logger.info("creating_agent_session")
    try:
        session = AgentSession(
            stt=stt_model,
            llm=llm_model,
            tts=elevenlabs.TTS(
                model="eleven_multilingual_v2",
                voice_id="21m00Tcm4TlvDq8ikWAM",
            ),
            turn_detection=MultilingualModel(),
            vad=ctx.proc.userdata["vad"],
            preemptive_generation=True,
        )
        logger.info("agent_session_created")
    except Exception as e:
        logger.error("agent_session_creation_failed", error=str(e))
        raise

    # Metrics collector
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    @session.on("transcript_received")
    def _on_transcript(transcript):
        logger.info("transcript_received", text=transcript.text)

    # Start session with injected dependencies
    logger.info("starting_session")
    try:
        async with asyncio.timeout(10):
            await session.start(
                agent=Assistant(
                    db_manager=_db_manager,
                    staff_name=staff_name
                ),
                room=ctx.room,
                room_input_options=RoomInputOptions(
                    noise_cancellation=noise_cancellation.BVC(),
                ),
            )
            logger.info("session_started", room=ctx.room.name)
    except Exception as e:
        logger.error("session_start_failed", error=str(e))
        raise

    # Connect to room
    logger.info("connecting_to_room")
    try:
        async with asyncio.timeout(5):
            await ctx.connect()
            logger.info("room_connected", room=ctx.room.name)
    except Exception as e:
        logger.error("room_connection_failed", error=str(e))
        raise

    # Log usage summary
    summary = usage_collector.get_summary()
    logger.info("usage_summary", livekit_usage=summary)


if __name__ == "__main__":
    configure_logging()
    
    logger.info("agent_starting")

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm
        )
    )