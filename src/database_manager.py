"""
Warehouse Inventory Database Manager

Features:
- In-memory fake inventory database for demo
- Simple item lookup by name with fuzzy matching
- Stock update operations (add/remove)
"""

import logging
from typing import List, Dict, Optional
from difflib import get_close_matches

logger = logging.getLogger("database")

# Fake inventory database
FAKE_INVENTORY_DB = [
    {
        "item_id": "STK-001",
        "name": "Fren Diski",
        "quantity": 145,
        "location": "Raf A3"
    },
    {
        "item_id": "STK-002",
        "name": "Yağ Filtresi",
        "quantity": 20,
        "location": "Raf B1"
    },
    {
        "item_id": "STK-003",
        "name": "V Kayışı",
        "quantity": 5,
        "location": "Depo Giriş"
    }
]


class DatabaseManager:
    """
    Simple inventory manager using in-memory fake database.
    
    Usage:
        db = DatabaseManager()
        item = await db.get_item("Fren Diski")
        success = await db.update_stock("STK-001", 10, "add")
    """

    def __init__(self):
        """Initialize database manager with fake inventory data."""
        self.inventory = FAKE_INVENTORY_DB
        logger.info("✅ Inventory database initialized with %d items", len(self.inventory))

    async def connect(self) -> None:
        """Verify database connection is working."""
        logger.info("✅ Database connection established (fake mode)")

    async def disconnect(self) -> None:
        """Gracefully close all database connections."""
        logger.info("Database connections closed")

    async def get_item(self, name: str) -> Optional[Dict]:
        """
        Find an inventory item by name using fuzzy matching.
        
        Args:
            name: Item name to search for (partial matches allowed).
            
        Returns:
            Item dictionary with keys: item_id, name, quantity, location
            Or None if not found.
        """
        if not name:
            return None

        # Try exact match first
        for item in self.inventory:
            if item["name"].lower() == name.lower():
                logger.info(f"Item found (exact): {item['name']}")
                return item

        # Try fuzzy matching
        item_names = [item["name"] for item in self.inventory]
        matches = get_close_matches(name, item_names, n=1, cutoff=0.6)
        
        if matches:
            matched_name = matches[0]
            for item in self.inventory:
                if item["name"] == matched_name:
                    logger.info(f"Item found (fuzzy): {item['name']} for query '{name}'")
                    return item

        logger.warning(f"Item not found: {name}")
        return None

    async def update_stock(
            self,
            item_id: str,
            quantity: int,
            operation: str
    ) -> bool:
        """
        Update stock quantity for an item.
        
        Args:
            item_id: The unique item identifier (e.g., "STK-001").
            quantity: Amount to add or remove.
            operation: Either "add" or "remove".
            
        Returns:
            True if updated successfully, False if item not found or invalid operation.
        """
        if operation not in ["add", "remove"]:
            logger.warning(f"Invalid operation: {operation}")
            return False

        for item in self.inventory:
            if item["item_id"] == item_id:
                old_quantity = item["quantity"]
                
                if operation == "add":
                    item["quantity"] += quantity
                elif operation == "remove":
                    if item["quantity"] >= quantity:
                        item["quantity"] -= quantity
                    else:
                        logger.warning(
                            f"Insufficient stock for {item['name']}: "
                            f"requested {quantity}, available {item['quantity']}"
                        )
                        return False

                logger.info(
                    f"✅ Stock updated: {item['name']} ({item_id}): "
                    f"{old_quantity} → {item['quantity']} ({operation} {quantity})"
                )
                return True

        logger.warning(f"Item not found: {item_id}")
        return False


# Singleton instance management
_db_instance: Optional[DatabaseManager] = None


def get_database() -> DatabaseManager:
    """
    Get the singleton DatabaseManager instance.
    
    Returns:
        DatabaseManager: The shared database manager.
    """
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseManager()
    return _db_instance


async def init_database() -> DatabaseManager:
    """
    Initialize and connect to the database.
    
    Convenience function for application startup.
    
    Returns:
        Connected DatabaseManager instance.
    """
    db = get_database()
    await db.connect()
    return db