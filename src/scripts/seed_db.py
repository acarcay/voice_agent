"""
Database Seeding Script

Seeds the database with sample appointments for testing the voice agent.

Usage:
    # Default: Add sample appointments for tomorrow
    python src/scripts/seed_db.py
    
    # Clear existing data first
    python src/scripts/seed_db.py --clear
    
    # Custom date offset (days from today)
    python src/scripts/seed_db.py --days 2
"""

import asyncio
import argparse
import sys
from datetime import datetime, timedelta, time as time_type
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(".env.local")

from sqlalchemy import delete
from database_manager import DatabaseManager
from models import Appointment, AppointmentStatus, CallLog, ConversationTranscript, AppointmentChange


# Sample appointment data
SAMPLE_APPOINTMENTS = [
    {
        "appointment_id": "randevu_001",
        "customer_name": "Ahmet Yılmaz",
        "phone": "+905551112233",
        "email": "ahmet@example.com",
        "time": time_type(14, 30),
        "status": AppointmentStatus.PENDING,
    },
    {
        "appointment_id": "randevu_002",
        "customer_name": "Zeynep Kaya",
        "phone": "+905554445566",
        "email": "zeynep@example.com",
        "time": time_type(16, 0),
        "status": AppointmentStatus.CONFIRMED,
    },
    {
        "appointment_id": "randevu_003",
        "customer_name": "Mehmet Demir",
        "phone": "+905557778899",
        "email": "mehmet@example.com",
        "time": time_type(10, 0),
        "status": AppointmentStatus.CANCELLED,
    },
    {
        "appointment_id": "randevu_004",
        "customer_name": "Ayşe Öztürk",
        "phone": "+905559990011",
        "email": "ayse@example.com",
        "time": time_type(11, 30),
        "status": AppointmentStatus.PENDING,
    },
    {
        "appointment_id": "randevu_005",
        "customer_name": "Ali Çelik",
        "phone": "+905553334455",
        "email": "ali@example.com",
        "time": time_type(15, 0),
        "status": AppointmentStatus.PENDING,
    },
]


async def clear_database(db: DatabaseManager) -> None:
    """Remove all existing data from tables."""
    print("🗑️  Clearing existing data...")
    
    async with db.session() as session:
        # Delete in order to respect foreign keys
        await session.execute(delete(ConversationTranscript))
        await session.execute(delete(CallLog))
        await session.execute(delete(AppointmentChange))
        await session.execute(delete(Appointment))
    
    print("✅ Database cleared")


async def seed_appointments(db: DatabaseManager, target_date: datetime.date) -> list:
    """Insert sample appointments for the target date."""
    print(f"📅 Seeding appointments for {target_date.isoformat()}...")
    
    created_ids = []
    
    async with db.session() as session:
        for data in SAMPLE_APPOINTMENTS:
            appointment = Appointment(
                appointment_id=data["appointment_id"],
                customer_name=data["customer_name"],
                phone=data["phone"],
                email=data["email"],
                appointment_date=target_date,
                appointment_time=data["time"],
                status=data["status"],
            )
            session.add(appointment)
            created_ids.append(data["appointment_id"])
            
            status_icon = {
                AppointmentStatus.PENDING: "⏳",
                AppointmentStatus.CONFIRMED: "✅",
                AppointmentStatus.CANCELLED: "❌",
            }.get(data["status"], "❓")
            
            print(f"  {status_icon} {data['appointment_id']}: {data['customer_name']} @ {data['time'].strftime('%H:%M')} [{data['status'].value}]")
    
    return created_ids


async def main():
    parser = argparse.ArgumentParser(description="Seed the voice agent database")
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing data before seeding"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Days from today for appointment date (default: 1 = tomorrow)"
    )
    args = parser.parse_args()
    
    print("=" * 60)
    print("🌱 Voice Agent Database Seeder")
    print("=" * 60)
    
    # Calculate target date
    target_date = (datetime.now() + timedelta(days=args.days)).date()
    print(f"📆 Target date: {target_date.isoformat()} ({args.days} day(s) from now)")
    
    # Connect to database
    try:
        db = DatabaseManager()
        await db.connect()
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        print("\n💡 Make sure DATABASE_URL is set in .env.local:")
        print("   DATABASE_URL=postgresql://voice_agent:voice_agent_dev@localhost:5432/voice_agent")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Connection error: {e}")
        print("\n💡 Make sure PostgreSQL is running:")
        print("   docker-compose up -d postgres")
        sys.exit(1)
    
    try:
        # Clear if requested
        if args.clear:
            await clear_database(db)
        
        # Seed appointments
        created_ids = await seed_appointments(db, target_date)
        
        print("\n" + "=" * 60)
        print("✅ Seeding complete!")
        print("=" * 60)
        print(f"\n📋 Created {len(created_ids)} appointments:")
        
        # Show pending appointments (testable via voice flow)
        pending_count = sum(
            1 for a in SAMPLE_APPOINTMENTS 
            if a["status"] == AppointmentStatus.PENDING
        )
        print(f"   ⏳ Pending (for voice confirmation): {pending_count}")
        
        print("\n🎯 To test the voice flow, use these pending appointment IDs:")
        for data in SAMPLE_APPOINTMENTS:
            if data["status"] == AppointmentStatus.PENDING:
                print(f"   - {data['appointment_id']} ({data['customer_name']})")
        
        print("\n📞 Start the agent and create a room with metadata:")
        print('   {"appointment_id": "randevu_001", "customer_name": "Ahmet Yılmaz", "time": "14:30"}')
        
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
