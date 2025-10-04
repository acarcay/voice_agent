import logging
import asyncio
import os
import json
from datetime import datetime
from typing import Optional

import elevenlabs
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

logger = logging.getLogger("agent")
load_dotenv(".env.local")

# Veritabanı simülasyonu - Production'da gerçek DB kullanın
FAKE_APPOINTMENTS_DB = [
    {"appointment_id": "randevu_101", "customer_name": "Ahmet Yılmaz", "time": "14:30", "status": "Beklemede"},
    {"appointment_id": "randevu_102", "customer_name": "Zeynep Kaya", "time": "16:00", "status": "Beklemede"},
]

# Konuşma kayıtları için
CONVERSATION_LOGS = []


# Metrikler için
class CallMetrics:
    def __init__(self):
        self.total_calls = 0
        self.confirmed = 0
        self.cancelled = 0
        self.rescheduled = 0
        self.no_response = 0
        self.call_durations = []

    def update(self, status: str, duration: float = 0):
        self.total_calls += 1
        if duration > 0:
            self.call_durations.append(duration)

        if status == "confirmed":
            self.confirmed += 1
        elif status == "cancelled":
            self.cancelled += 1
        elif status == "rescheduled":
            self.rescheduled += 1
        elif status == "no_response":
            self.no_response += 1

    def get_summary(self):
        avg_duration = sum(self.call_durations) / len(self.call_durations) if self.call_durations else 0
        return {
            "total_calls": self.total_calls,
            "confirmed": self.confirmed,
            "cancelled": self.cancelled,
            "rescheduled": self.rescheduled,
            "no_response": self.no_response,
            "average_duration_seconds": round(avg_duration, 2)
        }


call_metrics = CallMetrics()


class Assistant(Agent):
    def __init__(self, appointment_id: Optional[str] = None) -> None:
        self.appointment_id = appointment_id
        self.conversation_start_time = datetime.now()
        self.no_response_count = 0
        self.max_no_response = 3

        super().__init__(
            instructions=self._get_instructions(),
        )

    def _get_instructions(self) -> str:
        clinic_name = os.getenv("CLINIC_NAME", "Sağlık Kliniği")
        return f"""
        Senin adın Aslı. {clinic_name}'in randevu asistanısın.

        GÖREV AKIŞI:
        1. Kendini tanıt ve randevuyu bildir:
           "Merhaba [Ad] Bey/Hanım, ben Aslı, {clinic_name}'dan arıyorum. Yarın saat [Saat]'te randevunuz var."

        2. Teyit iste:
           "Randevunuza gelebilecek misiniz?"

        3. Cevaba göre aksiyon al:
           - EVET/GELECEĞİM/UYGUN → update_appointment_status('Onaylandı') çağır
             → "Harika! Teşekkür ederim, yarın görüşmek üzere. İyi günler!"
             → end_call('confirmed') çağır

           - HAYIR/ERTELEMEİSTİYORUM/BAŞKAZAMANA → find_available_slots() çağır
             → Seçenekleri sun: "Uygun tarihlerimiz: [tarihler]. Hangisi size uygun?"
             → Seçim yapılırsa → update_appointment_status('Ertelendi - [yeni_tarih]') çağır
             → end_call('rescheduled') çağır

           - İPTAL/İPTALEDİYORUM/GELEMİYORUM → update_appointment_status('İptal Edildi') çağır
             → "Anladım, randevunuzu iptal ediyorum. Geçmiş olsun, iyi günler."
             → end_call('cancelled') çağır

        KURALLAR:
        - Her yanıtı maksimum 2-3 cümle tut, kısa ve öz konuş
        - Nazik ve profesyonel ol ama aşırı samimi olma
        - Müşteri 3 kez yanıt vermezse: "Sizi rahatsız etmek istemedim, başka zaman tekrar arayacağım. İyi günler."
          → end_call('no_response') çağır
        - SADECE randevu konusunda konuş, başka konulara girme
        - Müşteri bilmediğin bir şey sorarsa: "Bu konuda bilgim yok, kliniği arayarak öğrenebilirsiniz"
        - Asla hakaret etme, tartışma veya sinirlenme

        ÖNEMLİ: Her aksiyon sonrası mutlaka ilgili function tool'ı çağır!
        """

    @function_tool
    async def get_appointment_details(self, context: RunContext, appointment_id: str):
        """
        Verilen randevu ID'sine ait müşteri adı ve randevu saatini getirir.

        Args:
            appointment_id: Randevu benzersiz kimliği

        Returns:
            Dict: Müşteri bilgileri veya hata mesajı
        """
        if not appointment_id or not isinstance(appointment_id, str):
            logger.error(f"Geçersiz appointment_id: {appointment_id}")
            return {"error": "Geçersiz randevu ID", "status": "Hata"}

        logger.info(f"Randevu detayları getiriliyor: {appointment_id}")

        try:
            for appt in FAKE_APPOINTMENTS_DB:
                if appt["appointment_id"] == appointment_id:
                    return {
                        "customer_name": appt['customer_name'],
                        "time": appt['time'],
                        "status": "Bulundu",
                        "current_status": appt.get('status', 'Beklemede')
                    }

            logger.warning(f"Randevu bulunamadı: {appointment_id}")
            return {"error": "Randevu bulunamadı.", "status": "Hata"}

        except Exception as e:
            logger.error(f"get_appointment_details hatası: {e}", exc_info=True)
            return {"error": f"Sistem hatası: {str(e)}", "status": "Hata"}

    @function_tool
    async def update_appointment_status(
            self,
            context: RunContext,
            appointment_id: str,
            status: str
    ):
        """
        Bir randevunun durumunu günceller.

        Args:
            appointment_id: Randevu ID
            status: Yeni durum ('Onaylandı', 'İptal Edildi', 'Ertelendi - [tarih]')

        Returns:
            Dict: İşlem sonucu
        """
        valid_statuses = ['Onaylandı', 'İptal Edildi']

        if not appointment_id:
            return {"error": "Appointment ID gerekli", "success": False}

        # Erteleme durumları için özel kontrol
        if not (status in valid_statuses or status.startswith('Ertelendi')):
            logger.warning(f"Geçersiz durum: {status}")
            return {"error": "Geçersiz durum", "success": False}

        logger.info(f"Randevu {appointment_id} durumu '{status}' olarak güncelleniyor.")

        try:
            # Veritabanı güncellemesi simülasyonu
            for appt in FAKE_APPOINTMENTS_DB:
                if appt["appointment_id"] == appointment_id:
                    appt["status"] = status
                    appt["updated_at"] = datetime.now().isoformat()

                    # Metrik güncelle
                    if status == "Onaylandı":
                        call_metrics.update("confirmed")
                    elif status == "İptal Edildi":
                        call_metrics.update("cancelled")
                    elif status.startswith("Ertelendi"):
                        call_metrics.update("rescheduled")

                    # Log kaydet
                    self._log_conversation_event("appointment_updated", {
                        "appointment_id": appointment_id,
                        "new_status": status
                    })

                    return {
                        "message": f"Randevu durumu başarıyla '{status}' olarak güncellendi.",
                        "success": True,
                        "appointment_id": appointment_id
                    }

            return {"error": "Randevu bulunamadı", "success": False}

        except Exception as e:
            logger.error(f"update_appointment_status hatası: {e}", exc_info=True)
            return {"error": f"Güncelleme başarısız: {str(e)}", "success": False}

    @function_tool
    async def find_available_slots(self, context: RunContext):
        """
        Müşterinin randevusunu ertelemek istemesi durumunda uygun olan
        en   yakın zaman dilimlerini bulur.

        Returns:
            Dict: Uygun zaman dilimleri listesi
        """
        logger.info("Uygun zaman dilimleri aranıyor...")

        try:
            # Gerçek uygulamada bu veritabanından gelecek
            available_slots = [
                "5 Ekim Cumartesi 11:00",
                "7 Ekim Pazartesi 09:30",
                "8 Ekim Salı 15:45"
            ]

            self._log_conversation_event("slots_requested", {
                "available_slots": available_slots
            })

            return {
                "slots": available_slots,
                "message": f"Şu tarihler uygun: {', '.join(available_slots)}",
                "success": True
            }

        except Exception as e:
            logger.error(f"find_available_slots hatası: {e}", exc_info=True)
            return {
                "error": "Uygun tarihler alınamadı",
                "success": False
            }

    @function_tool
    async def end_call(self, context: RunContext, reason: str):
        """
        Aramayı sonlandırır ve metrikleri kaydeder.

        Args:
            reason: Sonlandırma nedeni ('confirmed', 'cancelled', 'rescheduled', 'no_response', 'error')
        """
        duration = (datetime.now() - self.conversation_start_time).total_seconds()

        logger.info(f"Arama sonlandırılıyor. Sebep: {reason}, Süre: {duration}s")

        # Metrikleri güncelle
        call_metrics.update(reason, duration)

        # Son konuşma kaydı
        self._log_conversation_event("call_ended", {
            "reason": reason,
            "duration_seconds": duration,
            "appointment_id": self.appointment_id
        })

        # Session'ı kapat
        try:
            if hasattr(context, 'session') and context.session:
                await context.session.close()
        except Exception as e:
            logger.error(f"Session kapatma hatası: {e}")

        return {
            "message": "Arama sonlandırıldı",
            "reason": reason,
            "duration": duration
        }

    @function_tool
    async def handle_no_response(self, context: RunContext):
        """
        Müşteri yanıt vermediğinde çağrılır.
        """
        self.no_response_count += 1
        logger.warning(f"Yanıtsızlık sayısı: {self.no_response_count}/{self.max_no_response}")

        if self.no_response_count >= self.max_no_response:
            await self.end_call(context, "no_response")
            return {
                "message": "Maksimum yanıtsızlık sayısına ulaşıldı, arama sonlandırılıyor",
                "should_end": True
            }

        return {
            "message": f"Yanıtsızlık kaydedildi ({self.no_response_count}/{self.max_no_response})",
            "should_end": False
        }

    def _log_conversation_event(self, event_type: str, data: dict):
        """Konuşma olaylarını kaydet"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "appointment_id": self.appointment_id,
            "event_type": event_type,
            "data": data
        }
        CONVERSATION_LOGS.append(log_entry)

        # Gerçek uygulamada bu veritabanına yazılmalı
        logger.debug(f"Konuşma olayı kaydedildi: {event_type}")


def prewarm(proc: JobProcess):
    """Agent başlatılmadan önce gerekli kaynakları yükle"""
    logger.info("Prewarm başlatılıyor...")
    proc.userdata["vad"] = silero.VAD.load(sensitivity=0.5)
    logger.info("VAD modeli yüklendi")


async def entrypoint(ctx: JobContext):
    """Agent'ın ana giriş noktası"""
    ctx.log_context_fields = {"room": ctx.room.name}

    # Room metadata'dan appointment_id'yi al
    appointment_id = None
    try:
        metadata = ctx.room.metadata
        if metadata:
            metadata_dict = json.loads(metadata)
            appointment_id = metadata_dict.get("appointment_id")
            logger.info(f"Appointment ID alındı: {appointment_id}")
    except Exception as e:
        logger.warning(f"Metadata parsing hatası: {e}")

    # STT ve LLM modellerini çevre değişkenlerinden oku
    stt_model = os.getenv("STT_MODEL", "deepgram/nova-2-streaming:tr")
    llm_model = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")

    logger.info(f"STT Model: {stt_model}, LLM Model: {llm_model}")

    # ElevenLabs ayarları
    elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY")
    if not elevenlabs_api_key:
        logger.error("ELEVENLABS_API_KEY bulunamadı!")
        raise ValueError("ELEVENLABS_API_KEY gerekli")

    # AgentSession'ı kur
    session = AgentSession(
        stt=stt_model,
        llm=llm_model,
        tts=elevenlabs.TTS(
            model_id="eleven_multilingual_v2",
            voice_id="21m00Tcm4TlvDq8ikWAM",  # Rachel - profesyonel ses
            # Alternatif Türkçe sesler:
            # voice_id="pNInz6obpgDQGcFmaJgB" # Adam (erkek)
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    @session.on("transcript_received")
    def _on_transcript(transcript):
        """Transkriptleri kaydet"""
        logger.info(f"Transkript: {transcript.text}")
        # Gerçek uygulamada veritabanına kaydet

    async def log_usage():
        """Kullanım istatistiklerini kaydet"""
        summary = usage_collector.get_summary()
        metrics_summary = call_metrics.get_summary()

        logger.info(f"Agent Usage: {summary}")
        logger.info(f"Call Metrics: {metrics_summary}")

        try:
            combined_metadata = {
                "usage_summary": summary,
                "call_metrics": metrics_summary,
                "conversation_logs": CONVERSATION_LOGS[-10:]  # Son 10 olay
            }
            await ctx.room.send_participant_metadata(json.dumps(combined_metadata))
        except Exception as e:
            logger.warning(f"Metadata gönderme hatası: {e}")

    ctx.add_shutdown_callback(log_usage)

    # Session'ı başlat
    try:
        await session.start(
            agent=Assistant(appointment_id=appointment_id),
            room=ctx.room,
            room_input_options=RoomInputOptions(
                noise_cancellation=noise_cancellation.BVC(),
                audio_profile="telephony",
            ),
        )
        logger.info(f"Session başarıyla başlatıldı: {ctx.room.name}")
    except Exception as e:
        logger.error(f"Session başlatma hatası: {e}", exc_info=True)
        raise

    # Bağlantıyı kur
    try:
        await ctx.connect()
        logger.info(f"Bağlantı kuruldu: {ctx.room.name}")
    except Exception as e:
        logger.error(f"Bağlantı hatası: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    log_level = os.getenv("LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    logger.info("Agent başlatılıyor...")
    logger.info(f"Log seviyesi: {log_level}")

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            max_sessions=10
        )
    )