class InventoryDomainError(Exception):
    code = "INVENTORY_ERROR"
    default_message = "An inventory error occurred."

    def __init__(self, message: str | None = None, details: list[dict] | None = None):
        self.message = message or self.default_message
        self.details = details or []
        super().__init__(self.message)


class InvalidInventoryAdjustment(InventoryDomainError):
    code = "INVALID_INVENTORY_ADJUSTMENT"
    default_message = "Inventory adjustment is not valid."


class InactiveProduct(InventoryDomainError):
    code = "INACTIVE_PRODUCT"
    default_message = "Cannot adjust inventory for an inactive product."


class InactiveWarehouse(InventoryDomainError):
    code = "INACTIVE_WAREHOUSE"
    default_message = "Cannot adjust inventory in an inactive warehouse."


class InventoryNotFound(InventoryDomainError):
    code = "INVENTORY_NOT_FOUND"
    default_message = "Inventory record was not found."
