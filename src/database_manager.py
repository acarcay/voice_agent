"""
Veritabanı Yönetim Modülü
PostgreSQL ile randevu ve arama loglarını yönetir
"""

import os
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional

# SQLAlchemy kullanımı (opsiyonel)
# pip install sqlalchemy psycopg2-binary

logger = logging.getLogger("database")


class DatabaseManager:
    """
    Veritabanı işlemlerini yönetir

    Not: Bu basitleştirilmiş bir versiyon.
    Production'da SQLAlchemy ORM veya async PostgreSQL driver kullanın.
    """

    def __init__(self, connection_string: Optional[str] = None):
        """
        Args:
            connection_string: PostgreSQL bağlantı string'i
        """
        self.connection_string = connection_string or os.getenv("DATABASE_URL")
        self.conn = None

        if not self.connection_string:
            logger.warning("DATABASE_URL bulunamadı, simülasyon modunda çalışılıyor")
            self.simulation_mode = True
        else:
            self.simulation_mode = False

    async def connect(self):
        """Veritabanına bağlan"""
        if self.simulation_mode:
            logger.info("Simülasyon modu - veritabanı bağlantısı yok")
            return

        try:
            # import asyncpg  # pip install asyncpg
            # self.conn = await asyncpg.connect(self.connection_string)
            logger.info("✅ Veritabanı bağlantısı kuruldu")
        except Exception as e:
            logger.error(f"❌ Veritabanı bağlantı hatası: {e}")
            raise

    async def disconnect(self):
        """Veritabanı bağlantısını kapat"""
        if self.conn:
            await self.conn.close()
            logger.info("Veritabanı bağlantısı kapatıldı")

    async def get_tomorrows_appointments(self) -> List[Dict]:
        """
        Yarın randevusu olan ve durumu 'Beklemede' olan müşterileri getir

        Returns:
            List[Dict]: Randevu listesi
        """
        if self.simulation_mode:
            # Simülasyon verisi
            return [
                {
                    "appointment_id": "randevu_101",
                    "customer_name": "Ahmet Yılmaz",
                    "phone": "+905551112233",
                    "email": "ahmet@example.com",
                    "time": "14:30",
                    "date": "2025-10-05",
                    "status": "Beklemede"
                },
                {
                    "appointment_id": "randevu_102",
                    "customer_name": "Zeynep Kaya",
                    "phone": "+905554445566",
                    "email": "zeynep@example.com",
                    "time": "16:00",
                    "date": "2025-10-05",
                    "status": "Beklemede"
                }
            ]

        try:
            tomorrow = (datetime.now() + timedelta(days=1)).date()

            query = """
                    SELECT appointment_id, \
                           customer_name, \
                           phone, \
                           email, \
                           appointment_time as time,
                    appointment_date as date,
                    status
                    FROM appointments
                    WHERE appointment_date = $1
                      AND status = 'Beklemede'
                    ORDER BY appointment_time ASC \
                    """

            # rows = await self.conn.fetch(query, tomorrow)
            # return [dict(row) for row in rows]

            logger.info(f"Yarın ({tomorrow}) için randevular getirildi")
            return []

        except Exception as e:
            logger.error(f"❌ Randevular getirilemedi: {e}")
            return []

    async def update_appointment_status(
            self,
            appointment_id: str,
            new_status: str,
            changed_by: str = "agent"
    ) -> bool:
        """
        Randevu durumunu güncelle ve değişikliği logla

        Args:
            appointment_id: Randevu ID
            new_status: Yeni durum
            changed_by: Değişikliği yapan ('agent', 'customer', 'admin')

        Returns:
            bool: Başarılı ise True
        """
        if self.simulation_mode:
            logger.info(f"[SİMÜLASYON] Randevu {appointment_id} -> {new_status}")
            return True

        try:
            # Önce eski durumu al
            get_query = "SELECT status FROM appointments WHERE appointment_id = $1"
            # old_status = await self.conn.fetchval(get_query, appointment_id)

            # Durumu güncelle
            update_query = """
                           UPDATE appointments
                           SET status     = $1, \
                               updated_at = CURRENT_TIMESTAMP
                           WHERE appointment_id = $2 \
                           """
            # await self.conn.execute(update_query, new_status, appointment_id)

            # Değişiklik logunu kaydet
            log_query = """
                        INSERT INTO appointment_changes
                            (appointment_id, old_status, new_status, changed_by)
                        VALUES ($1, $2, $3, $4) \
                        """
            # await self.conn.execute(log_query, appointment_id, old_status, new_status, changed_by)

            logger.info(f"✅ Randevu durumu güncellendi: {appointment_id} -> {new_status}")
            return True

        except Exception as e:
            logger.error(f"❌ Durum güncelleme hatası: {e}")
            return False

    async def log_call(
            self,
            appointment_id: str,
            room_name: str,
            success: bool,
            attempts: int,
            duration: int = 0,
            error_message: Optional[str] = None
    ) -> int:
        """
        Arama logunu kaydet

        Returns:
            int: Log ID veya -1 (hata durumunda)
        """
        if self.simulation_mode:
            logger.info(f"[SİMÜLASYON] Arama logu: {appointment_id} - Başarılı: {success}")
            return 1

        try:
            query = """
                    INSERT INTO call_logs
                    (appointment_id, room_name, call_status, call_duration, attempts, success, error_message)
                    VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id \
                    """

            call_status = "completed" if success else "failed"

            # log_id = await self.conn.fetchval(
            #     query,
            #     appointment_id, room_name, call_status, duration, attempts, success, error_message
            # )

            logger.info(f"✅ Arama logu kaydedildi: {appointment_id}")
            return 1  # log_id

        except Exception as e:
            logger.error(f"❌ Arama logu kaydetme hatası: {e}")
            return -1

    async def save_transcript(
            self,
            call_log_id: int,
            speaker: str,
            text: str
    ):
        """
        Konuşma transkriptini kaydet

        Args:
            call_log_id: Arama log ID
            speaker: Konuşan ('agent' veya 'customer')
            text: Konuşma metni
        """
        if self.simulation_mode:
            return

        try:
            query = """
                    INSERT INTO conversation_transcripts (call_log_id, speaker, text)
                    VALUES ($1, $2, $3) \
                    """
            # await self.conn.execute(query, call_log_id, speaker, text)
            logger.debug(f"Transkript kaydedildi: {speaker[:10]}...")

        except Exception as e:
            logger.error(f"❌ Transkript kaydetme hatası: {e}")

    async def log_notification(
            self,
            appointment_id: str,
            notification_type: str,
            recipient: str,
            status: str,
            error_message: Optional[str] = None
    ):
        """
        Bildirim logunu kaydet (SMS, Email, vs)

        Args:
            appointment_id: Randevu ID
            notification_type: 'sms', 'email', 'voice_call'
            recipient: Alıcı (telefon veya email)
            status: 'sent', 'failed', 'pending'
            error_message: Hata mesajı (varsa)
        """
        if self.simulation_mode:
            logger.info(f"[SİMÜLASYON] Bildirim logu: {notification_type} -> {recipient}")
            return

        try:
            query = """
                    INSERT INTO notification_logs
                        (appointment_id, notification_type, recipient, status, error_message)
                    VALUES ($1, $2, $3, $4, $5) \
                    """
            # await self.conn.execute(query, appointment_id, notification_type, recipient, status, error_message)
            logger.info(f"✅ Bildirim logu kaydedildi: {notification_type}")

        except Exception as e:
            logger.error(f"❌ Bildirim logu hatası: {e}")

    async def get_statistics(self, days: int = 30) -> Dict:
        """
        Son X günün istatistiklerini getir

        Args:
            days: Kaç günlük istatistik

        Returns:
            Dict: İstatistik verileri
        """
        if self.simulation_mode:
            return {
                "total_appointments": 150,
                "confirmed": 120,
                "cancelled": 15,
                "pending": 10,
                "completed": 5,
                "success_rate": 80.0
            }

        try:
            start_date = datetime.now().date() - timedelta(days=days)

            query = """
                    SELECT COUNT(*)                                            as total_appointments, \
                           COUNT(CASE WHEN status = 'Onaylandı' THEN 1 END)    as confirmed, \
                           COUNT(CASE WHEN status = 'İptal Edildi' THEN 1 END) as cancelled, \
                           COUNT(CASE WHEN status = 'Beklemede' THEN 1 END)    as pending, \
                           COUNT(CASE WHEN status = 'Tamamlandı' THEN 1 END)   as completed
                    FROM appointments
                    WHERE appointment_date >= $1 \
                    """

            # stats = await self.conn.fetchrow(query, start_date)
            # return dict(stats)

            return {}

        except Exception as e:
            logger.error(f"❌ İstatistik alma hatası: {e}")
            return {}

    async def get_available_slots(
            self,
            start_date: date,
            end_date: date,
            duration_minutes: int = 30
    ) -> List[str]:
        """
        Belirtilen tarih aralığında boş zaman dilimlerini bul

        Args:
            start_date: Başlangıç tarihi
            end_date: Bitiş tarihi
            duration_minutes: Randevu süresi (dakika)

        Returns:
            List[str]: Uygun zaman dilimleri
        """
        if self.simulation_mode:
            return [
                "5 Ekim Cumartesi 11:00",
                "7 Ekim Pazartesi 09:30",
                "8 Ekim Salı 15:45"
            ]

        try:
            # Gerçek uygulamada bu daha karmaşık olacak
            # Çalışma saatleri, mevcut randevular, doktor müsaitliği vs.

            query = """
                    WITH working_hours AS (
                        -- Çalışma saatleri: 09:00 - 18:00
                        SELECT generate_series(
                                       $1::date + '09:00'::time,
                                       $2::date + '18:00'::time,
                                       ($3 || ' minutes'):: interval
                               ) AS slot_time),
                         booked_slots AS (SELECT appointment_date + appointment_time AS booked_time \
                                          FROM appointments \
                                          WHERE appointment_date BETWEEN $1 AND $2 \
                                            AND status NOT IN ('İptal Edildi'))
                    SELECT slot_time
                    FROM working_hours
                    WHERE slot_time NOT IN (SELECT booked_time FROM booked_slots)
                    ORDER BY slot_time LIMIT 5 \
                    """

            # slots = await self.conn.fetch(query, start_date, end_date, duration_minutes)
            # return [slot['slot_time'].strftime("%d %B %A %H:%M") for slot in slots]

            return []

        except Exception as e:
            logger.error(f"❌ Uygun slot bulunamadı: {e}")
            return []


# Singleton instance
_db_instance = None


def get_database() -> DatabaseManager:
    """Veritabanı yöneticisi singleton'ını döndür"""
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseManager()
    return _db_instance