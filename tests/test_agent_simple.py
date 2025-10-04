"""
Basit Agent Test Script - Hızlı Test İçin
pytest gerektirmez, doğrudan çalıştırılabilir
"""

import asyncio
import sys
from datetime import datetime


class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []

    def run_test(self, name, test_func):
        """Test çalıştır"""
        print(f"\n{'=' * 60}")
        print(f"🧪 TEST: {name}")
        print(f"{'=' * 60}")

        try:
            result = asyncio.run(test_func())
            if result:
                print(f"✅ PASSED")
                self.passed += 1
                self.tests.append({"name": name, "status": "PASSED"})
            else:
                print(f"❌ FAILED")
                self.failed += 1
                self.tests.append({"name": name, "status": "FAILED"})
        except Exception as e:
            print(f"❌ ERROR: {str(e)}")
            self.failed += 1
            self.tests.append({"name": name, "status": "ERROR", "error": str(e)})

    def print_summary(self):
        """Özet yazdır"""
        total = self.passed + self.failed
        success_rate = (self.passed / total * 100) if total > 0 else 0

        print("\n" + "=" * 60)
        print("📊 TEST SONUÇLARI")
        print("=" * 60)
        print(f"Toplam: {total}")
        print(f"✅ Başarılı: {self.passed}")
        print(f"❌ Başarısız: {self.failed}")
        print(f"📈 Başarı Oranı: {success_rate:.1f}%")
        print("=" * 60)

        return self.failed == 0


# ==================== MOCK CONTEXT ====================

class MockContext:
    """Test için mock context"""
    session = None

    async def close(self):
        pass


# ==================== TEST FONKSİYONLARI ====================

async def test_imports():
    """Module import testi"""
    try:
        from agent import Assistant
        print("✓ agent.py import edildi")

        from database_manager import DatabaseManager
        print("✓ database_manager.py import edildi")

        return True
    except ImportError as e:
        print(f"✗ Import hatası: {e}")
        return False


async def test_assistant_creation():
    """Assistant oluşturma testi"""
    try:
        from agent import Assistant

        assistant = Assistant()
        print(f"✓ Assistant oluşturuldu (ID: {assistant.appointment_id})")

        assistant_with_id = Assistant(appointment_id="test_123")
        print(f"✓ Assistant ID ile oluşturuldu: {assistant_with_id.appointment_id}")

        return True
    except Exception as e:
        print(f"✗ Hata: {e}")
        return False


async def test_get_appointment_details():
    """Randevu detayları getirme testi"""
    try:
        from agent import Assistant

        assistant = Assistant()
        context = MockContext()

        # Var olan randevu
        result = await assistant.get_appointment_details(context, "randevu_101")
        if result["status"] != "Bulundu":
            print(f"✗ Randevu bulunamadı")
            return False
        print(f"✓ Randevu bulundu: {result['customer_name']} - {result['time']}")

        # Olmayan randevu
        result = await assistant.get_appointment_details(context, "randevu_999")
        if result["status"] != "Hata":
            print(f"✗ Hata kontrolü başarısız")
            return False
        print(f"✓ Olmayan randevu kontrolü başarılı")

        return True
    except Exception as e:
        print(f"✗ Hata: {e}")
        return False


async def test_update_appointment_status():
    """Randevu durumu güncelleme testi"""
    try:
        from agent import Assistant

        assistant = Assistant()
        context = MockContext()

        # Onaylama
        result = await assistant.update_appointment_status(
            context, "randevu_101", "Onaylandı"
        )
        if not result["success"]:
            print(f"✗ Onaylama başarısız")
            return False
        print(f"✓ Randevu onaylandı")

        # İptal
        result = await assistant.update_appointment_status(
            context, "randevu_102", "İptal Edildi"
        )
        if not result["success"]:
            print(f"✗ İptal başarısız")
            return False
        print(f"✓ Randevu iptal edildi")

        return True
    except Exception as e:
        print(f"✗ Hata: {e}")
        return False


async def test_find_available_slots():
    """Uygun slot bulma testi"""
    try:
        from agent import Assistant

        assistant = Assistant()
        context = MockContext()

        result = await assistant.find_available_slots(context)
        if not result.get("success") or not result.get("slots"):
            print(f"✗ Slot bulunamadı")
            return False

        print(f"✓ {len(result['slots'])} uygun slot bulundu:")
        for slot in result["slots"]:
            print(f"  - {slot}")

        return True
    except Exception as e:
        print(f"✗ Hata: {e}")
        return False


async def test_end_call():
    """Arama sonlandırma testi"""
    try:
        from agent import Assistant

        assistant = Assistant(appointment_id="test_001")
        context = MockContext()

        result = await assistant.end_call(context, "confirmed")
        if result["reason"] != "confirmed":
            print(f"✗ Sonlandırma başarısız")
            return False

        print(f"✓ Arama sonlandırıldı: {result['reason']}")
        print(f"✓ Süre: {result['duration']:.2f}s")

        return True
    except Exception as e:
        print(f"✗ Hata: {e}")
        return False


async def test_handle_no_response():
    """Yanıtsızlık yönetimi testi"""
    try:
        from agent import Assistant

        assistant = Assistant()
        context = MockContext()

        # 1. deneme
        result = await assistant.handle_no_response(context)
        if result["should_end"]:
            print(f"✗ Erken sonlandırma")
            return False
        print(f"✓ 1. yanıtsızlık kaydedildi")

        # 2. deneme
        result = await assistant.handle_no_response(context)
        if result["should_end"]:
            print(f"✗ Erken sonlandırma")
            return False
        print(f"✓ 2. yanıtsızlık kaydedildi")

        # 3. deneme - sonlanmalı
        result = await assistant.handle_no_response(context)
        if not result["should_end"]:
            print(f"✗ 3. denemede sonlanmadı")
            return False
        print(f"✓ 3. yanıtsızlık sonrası sonlandırma")

        return True
    except Exception as e:
        print(f"✗ Hata: {e}")
        return False


async def test_database_manager():
    """Database manager testi"""
    try:
        from database_manager import DatabaseManager

        db = DatabaseManager()
        await db.connect()
        print(f"✓ Database bağlantısı kuruldu (Simülasyon: {db.simulation_mode})")

        # Randevuları al
        appointments = await db.get_tomorrows_appointments()
        print(f"✓ {len(appointments)} randevu bulundu")

        if appointments:
            # İlk randevuyu güncelle
            appt = appointments[0]
            success = await db.update_appointment_status(
                appt['appointment_id'],
                'Onaylandı',
                'test'
            )
            if success:
                print(f"✓ Randevu durumu güncellendi")

        await db.disconnect()
        return True
    except Exception as e:
        print(f"✗ Hata: {e}")
        return False


async def test_metrics():
    """Metrik sistemi testi"""
    try:
        from agent import CallMetrics

        metrics = CallMetrics()

        # Test verileri
        metrics.update("confirmed", 45.5)
        metrics.update("confirmed", 32.1)
        metrics.update("cancelled", 15.0)
        metrics.update("no_response", 10.0)

        summary = metrics.get_summary()
        print(f"✓ Toplam arama: {summary['total_calls']}")
        print(f"✓ Onaylanan: {summary['confirmed']}")
        print(f"✓ İptal: {summary['cancelled']}")
        print(f"✓ Yanıtsız: {summary['no_response']}")
        print(f"✓ Ortalama süre: {summary['average_duration_seconds']}s")

        return summary['total_calls'] == 4
    except Exception as e:
        print(f"✗ Hata: {e}")
        return False


async def test_response_time():
    """Yanıt süresi testi"""
    try:
        from agent import Assistant

        assistant = Assistant()
        context = MockContext()

        start = datetime.now()
        result = await assistant.get_appointment_details(context, "randevu_101")
        duration = (datetime.now() - start).total_seconds()

        print(f"✓ Yanıt süresi: {duration * 1000:.2f}ms")

        if duration > 0.5:
            print(f"⚠ Yavaş yanıt (>500ms)")
            return False

        return True
    except Exception as e:
        print(f"✗ Hata: {e}")
        return False


async def test_concurrent_calls():
    """Eş zamanlı çağrı testi"""
    try:
        from agent import Assistant

        assistant = Assistant()
        context = MockContext()

        # 10 eş zamanlı çağrı
        tasks = [
            assistant.get_appointment_details(context, "randevu_101")
            for _ in range(10)
        ]

        start = datetime.now()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        duration = (datetime.now() - start).total_seconds()

        errors = [r for r in results if isinstance(r, Exception)]
        successful = len(results) - len(errors)

        print(f"✓ {successful}/{len(results)} başarılı")
        print(f"✓ Toplam süre: {duration:.2f}s")

        if errors:
            print(f"⚠ {len(errors)} hata oluştu")
            for error in errors[:3]:  # İlk 3 hatayı göster
                print(f"  - {error}")

        return len(errors) == 0
    except Exception as e:
        print(f"✗ Hata: {e}")
        return False


# ==================== ANA FONKSİYON ====================

def main():
    """Tüm testleri çalıştır"""
    print("\n" + "=" * 60)
    print("🚀 AGENT TEST SÜİTİ BAŞLATILIYOR")
    print("=" * 60)

    runner = TestRunner()

    # Testleri çalıştır
    runner.run_test("Module Imports", test_imports)
    runner.run_test("Assistant Creation", test_assistant_creation)
    runner.run_test("Get Appointment Details", test_get_appointment_details)
    runner.run_test("Update Appointment Status", test_update_appointment_status)
    runner.run_test("Find Available Slots", test_find_available_slots)
    runner.run_test("End Call", test_end_call)
    runner.run_test("Handle No Response", test_handle_no_response)
    runner.run_test("Database Manager", test_database_manager)
    runner.run_test("Metrics System", test_metrics)
    runner.run_test("Response Time", test_response_time)
    runner.run_test("Concurrent Calls", test_concurrent_calls)

    # Özet
    success = runner.print_summary()

    if success:
        print("\n✅ Tüm testler başarılı!")
        sys.exit(0)
    else:
        print("\n❌ Bazı testler başarısız!")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️  Test durduruldu")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Kritik hata: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)