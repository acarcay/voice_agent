import asyncio
import os
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from dotenv import load_dotenv
from livekit.api import LiveKitAPI, CreateRoomRequest, RoomConfiguration

# .env.local dosyasındaki çevre değişkenlerini yükle
load_dotenv(".env.local")

# Logging ayarları
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("call_initiator")

# Çevre değişkenleri
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "http://localhost:7880")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")

# Twilio ayarları (opsiyonel - gerçek telefon için)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

# Anahtarların kontrolü
if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
    logger.error("HATA: LIVEKIT_API_KEY ve LIVEKIT_API_SECRET değişkenleri .env.local dosyasında bulunamadı.")
    exit(1)

# Simüle edilmiş randevu veritabanı
FAKE_APPOINTMENTS_DB = [
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
    },
]

# Arama sonuçları
CALL_RESULTS = []


class CallManager:
    """Arama yönetimi için sınıf"""

    def __init__(self, lk_api: LiveKitAPI):
        self.lk_api = lk_api
        self.active_rooms = []
        self.max_retries = 3
        self.retry_delay = 5  # saniye

    async def create_room_for_appointment(
            self,
            appointment: Dict
    ) -> Optional[str]:
        """
        Randevu için bir LiveKit odası oluştur

        Args:
            appointment: Randevu bilgileri

        Returns:
            str: Oda adı veya None (hata durumunda)
        """
        room_name = f"confirmation_call_{appointment['appointment_id']}"

        try:
            # Oda metadata'sı
            metadata = {
                "appointment_id": appointment["appointment_id"],
                "customer_name": appointment["customer_name"],
                "task": "confirm_appointment",
                "created_at": datetime.now().isoformat()
            }

            # Oda konfigürasyonu
            room_config = RoomConfiguration(
                name=room_name,
                empty_timeout=300,  # 5 dakika boş kalırsa otomatik kapat
                max_participants=2,  # Sadece asistan ve müşteri
            )

            room = await self.lk_api.room.create_room(
                CreateRoomRequest(
                    name=room_name,
                    metadata=json.dumps(metadata)
                )
            )

            logger.info(f"✅ Oda oluşturuldu: {room.name} ({appointment['customer_name']})")
            self.active_rooms.append(room_name)
            return room_name

        except Exception as e:
            logger.error(f"❌ Oda oluşturma hatası: {e}")
            # Oda zaten varsa devam et
            if "already exists" in str(e).lower():
                logger.info(f"⚠️  Oda zaten mevcut: {room_name}")
                return room_name
            return None

    async def place_call_simulation(
            self,
            phone_number: str,
            room_name: str,
            appointment: Dict
    ) -> bool:
        """
        Simüle edilmiş telefon araması
        Gerçek uygulamada Twilio/LiveKit SIP kullanılacak

        Args:
            phone_number: Aranacak numara
            room_name: Bağlanacak oda
            appointment: Randevu bilgileri

        Returns:
            bool: Başarılı ise True
        """
        logger.info(f"📞 SİMÜLASYON: {phone_number} numarası aranıyor...")
        logger.info(f"   Müşteri: {appointment['customer_name']}")
        logger.info(f"   Oda: {room_name}")

        await asyncio.sleep(2)  # Arama simülasyonu

        # %90 başarı oranı simülasyonu
        import random
        success = random.random() > 0.1

        if success:
            logger.info(f"✅ Arama başarılı - Katılımcı odaya yönlendirildi")
            return True
        else:
            logger.warning(f"⚠️  Arama başarısız - Numara meşgul veya ulaşılamıyor")
            return False

    async def place_call_twilio(
            self,
            phone_number: str,
            room_name: str,
            appointment: Dict
    ) -> bool:
        """
        Twilio ile gerçek telefon araması yap (opsiyonel)

        Not: Bu fonksiyonu kullanmak için:
        1. pip install twilio
        2. TWILIO_* çevre değişkenlerini ayarla
        3. TwiML webhook URL'i ayarla
        """
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
            logger.warning("Twilio bilgileri eksik, simülasyon moduna geçiliyor")
            return await self.place_call_simulation(phone_number, room_name, appointment)

        try:
            # Twilio import (opsiyonel)
            # from twilio.rest import Client
            # client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

            # TwiML URL - LiveKit'e bağlanacak
            twiml_url = f"{os.getenv('SERVER_URL')}/twiml/{room_name}"

            logger.info(f"📞 TWILIO: {phone_number} aranıyor...")

            # call = client.calls.create(
            #     to=phone_number,
            #     from_=TWILIO_PHONE_NUMBER,
            #     url=twiml_url,
            #     timeout=30
            # )

            # logger.info(f"✅ Twilio arama başlatıldı: {call.sid}")
            # return True

            # Şimdilik simülasyon
            return await self.place_call_simulation(phone_number, room_name, appointment)

        except Exception as e:
            logger.error(f"❌ Twilio arama hatası: {e}")
            return False

    async def place_call_with_retry(
            self,
            appointment: Dict,
            room_name: str
    ) -> Dict:
        """
        Yeniden deneme mekanizmalı arama

        Returns:
            Dict: Arama sonucu
        """
        phone_number = appointment["phone"]

        for attempt in range(1, self.max_retries + 1):
            logger.info(f"🔄 Arama denemesi {attempt}/{self.max_retries}")

            try:
                success = await self.place_call_simulation(
                    phone_number, room_name, appointment
                )

                if success:
                    return {
                        "success": True,
                        "appointment_id": appointment["appointment_id"],
                        "attempts": attempt,
                        "timestamp": datetime.now().isoformat()
                    }

                if attempt < self.max_retries:
                    logger.info(f"⏳ {self.retry_delay} saniye bekleniyor...")
                    await asyncio.sleep(self.retry_delay)

            except Exception as e:
                logger.error(f"❌ Arama hatası (deneme {attempt}): {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay)

        # Tüm denemeler başarısız
        logger.error(f"❌ Tüm arama denemeleri başarısız: {appointment['customer_name']}")
        return {
            "success": False,
            "appointment_id": appointment["appointment_id"],
            "attempts": self.max_retries,
            "error": "Max retry exceeded",
            "timestamp": datetime.now().isoformat()
        }

    async def cleanup_room(self, room_name: str):
        """Odayı temizle"""
        try:
            await self.lk_api.room.delete_room(room_name)
            logger.info(f"🧹 Oda silindi: {room_name}")
            if room_name in self.active_rooms:
                self.active_rooms.remove(room_name)
        except Exception as e:
            logger.warning(f"Oda silme hatası: {e}")


async def get_tomorrows_appointments() -> List[Dict]:
    """
    Yarın randevusu olan müşterileri getir

    Gerçek uygulamada bu fonksiyon:
    - Veritabanından yarının tarihine göre filtreleme yapacak
    - Sadece 'Beklemede' statusundeki randevuları çekecek

    Returns:
        List[Dict]: Yarın randevusu olan müşteri listesi
    """
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    logger.info(f"Yarın ({tomorrow}) için randevular aranıyor...")

    # Gerçek uygulamada SQL sorgusu:
    # SELECT * FROM appointments
    # WHERE date = ? AND status = 'Beklemede'
    # ORDER BY time ASC

    # Şimdilik fake DB'den filtreleme
    appointments = [
        appt for appt in FAKE_APPOINTMENTS_DB
        if appt.get("date") == tomorrow and appt.get("status") == "Beklemede"
    ]

    logger.info(f"✅ {len(appointments)} randevu bulundu")
    return appointments


async def save_call_result(result: Dict):
    """
    Arama sonucunu kaydet

    Args:
        result: Arama sonuç bilgileri
    """
    CALL_RESULTS.append(result)

    # Gerçek uygulamada veritabanına kaydet
    # await db.execute(
    #     "INSERT INTO call_logs (appointment_id, success, attempts, timestamp) VALUES (?, ?, ?, ?)",
    #     (result['appointment_id'], result['success'], result['attempts'], result['timestamp'])
    # )

    logger.debug(f"Arama sonucu kaydedildi: {result['appointment_id']}")


async def send_sms_backup(appointment: Dict):
    """
    Arama başarısız olursa SMS yedek bildirimi gönder

    Args:
        appointment: Randevu bilgileri
    """
    logger.info(f"📱 SMS yedek bildirimi gönderiliyor: {appointment['customer_name']}")

    # Gerçek uygulamada Twilio SMS veya başka bir SMS servisi
    # from twilio.rest import Client
    # client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    # message = client.messages.create(
    #     body=f"Merhaba {appointment['customer_name']}, yarın saat {appointment['time']}'te randevunuz var.",
    #     from_=TWILIO_PHONE_NUMBER,
    #     to=appointment['phone']
    # )

    await asyncio.sleep(1)  # Simülasyon
    logger.info(f"✅ SMS gönderildi: {appointment['phone']}")


async def send_email_backup(appointment: Dict):
    """
    Email yedek bildirimi gönder

    Args:
        appointment: Randevu bilgileri
    """
    logger.info(f"📧 Email bildirimi gönderiliyor: {appointment['email']}")

    # Gerçek uygulamada SMTP veya email servisi
    # import smtplib
    # from email.mime.text import MIMEText
    #
    # msg = MIMEText(f"Sayın {appointment['customer_name']}, yarın {appointment['time']}'te randevunuz var.")
    # msg['Subject'] = 'Randevu Hatırlatması'
    # msg['From'] = 'noreply@klinik.com'
    # msg['To'] = appointment['email']
    #
    # with smtplib.SMTP('localhost') as s:
    #     s.send_message(msg)

    await asyncio.sleep(1)  # Simülasyon
    logger.info(f"✅ Email gönderildi: {appointment['email']}")


def print_summary(results: List[Dict]):
    """
    Arama sonuçlarının özetini yazdır

    Args:
        results: Tüm arama sonuçları
    """
    total = len(results)
    successful = sum(1 for r in results if r['success'])
    failed = total - successful

    print("\n" + "=" * 60)
    print("📊 ARAMA SONUÇLARI ÖZETİ")
    print("=" * 60)
    print(f"Toplam Arama: {total}")
    print(f"✅ Başarılı: {successful} ({successful / total * 100:.1f}%)")
    print(f"❌ Başarısız: {failed} ({failed / total * 100:.1f}%)")
    print("=" * 60)

    if failed > 0:
        print("\n⚠️  Başarısız aramalar:")
        for result in results:
            if not result['success']:
                appt_id = result['appointment_id']
                print(f"  - {appt_id} (Deneme sayısı: {result['attempts']})")

    print()


async def main():
    """Ana fonksiyon - randevu teyit aramalarını başlatır"""
    logger.info("=" * 60)
    logger.info("🚀 RANDEVU TEYİT ARAMA SİSTEMİ BAŞLATILIYOR")
    logger.info("=" * 60)

    try:
        # LiveKit API'ye bağlan
        lk_api = LiveKitAPI(
            url=LIVEKIT_URL,
            api_key=LIVEKIT_API_KEY,
            api_secret=LIVEKIT_API_SECRET
        )
        logger.info(f"✅ LiveKit API bağlantısı kuruldu: {LIVEKIT_URL}")

        # Call Manager oluştur
        call_manager = CallManager(lk_api)

        # Yarın randevusu olan müşterileri al
        appointments = await get_tomorrows_appointments()

        if not appointments:
            logger.warning("⚠️  Yarın için randevu bulunamadı!")
            return

        logger.info(f"\n📋 {len(appointments)} müşteri ile iletişime geçilecek\n")

        # Her randevu için arama başlat
        for i, appointment in enumerate(appointments, 1):
            customer_name = appointment["customer_name"]
            appointment_id = appointment["appointment_id"]

            logger.info(f"\n{'─' * 60}")
            logger.info(f"📞 [{i}/{len(appointments)}] {customer_name} aranıyor...")
            logger.info(f"   Randevu ID: {appointment_id}")
            logger.info(f"   Saat: {appointment['time']}")
            logger.info(f"{'─' * 60}")

            try:
                # 1. LiveKit odası oluştur
                room_name = await call_manager.create_room_for_appointment(appointment)

                if not room_name:
                    logger.error(f"❌ Oda oluşturulamadı, sonraki randevuya geçiliyor")
                    await save_call_result({
                        "success": False,
                        "appointment_id": appointment_id,
                        "attempts": 0,
                        "error": "Room creation failed",
                        "timestamp": datetime.now().isoformat()
                    })
                    continue

                # 2. Agent'a oda bilgisini gönder (metadata zaten ayarlı)
                logger.info(f"🤖 Asistan Aslı'ya '{room_name}' odasına katılma görevi atandı")

                # 3. Telefon araması yap
                result = await call_manager.place_call_with_retry(appointment, room_name)
                await save_call_result(result)

                # 4. Başarısız ise yedek bildirimler gönder
                if not result['success']:
                    logger.warning(f"⚠️  Arama başarısız, yedek bildirimler gönderiliyor...")

                    # SMS ve Email paralel olarak gönder
                    await asyncio.gather(
                        send_sms_backup(appointment),
                        send_email_backup(appointment),
                        return_exceptions=True
                    )

                # 5. Sonraki aramaya geçmeden önce kısa bekleme
                if i < len(appointments):
                    delay = 5
                    logger.info(f"⏳ Sonraki aramaya kadar {delay} saniye bekleniyor...\n")
                    await asyncio.sleep(delay)

            except Exception as e:
                logger.error(f"❌ Beklenmeyen hata: {e}", exc_info=True)
                await save_call_result({
                    "success": False,
                    "appointment_id": appointment_id,
                    "attempts": 0,
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                })
                continue

        # Özet rapor
        print_summary(CALL_RESULTS)

        # Cleanup (opsiyonel)
        # for room_name in call_manager.active_rooms:
        #     await call_manager.cleanup_room(room_name)

        # API bağlantısını kapat
        await lk_api.close()
        logger.info("✅ Tüm aramalar tamamlandı, sistem kapatılıyor")

    except Exception as e:
        logger.error(f"❌ Kritik hata: {e}", exc_info=True)
        raise


async def schedule_daily_calls():
    """
    Günlük otomatik arama zamanlaması

    Gerçek uygulamada:
    - Cron job olarak çalıştırılabilir
    - Veya APScheduler ile Python içinden zamanlanabilir
    """
    # pip install apscheduler
    # from apscheduler.schedulers.asyncio import AsyncIOScheduler
    #
    # scheduler = AsyncIOScheduler()
    # scheduler.add_job(main, 'cron', hour=10, minute=0)  # Her gün 10:00'da
    # scheduler.start()

    pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n⚠️  Kullanıcı tarafından durduruldu")
    except Exception as e:
        logger.error(f"❌ Program hatası: {e}", exc_info=True)
        exit(1)