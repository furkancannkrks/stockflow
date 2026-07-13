class StockFlowDomainError(Exception):
    code = "DOMAIN_ERROR"
    default_message = "A domain error occurred."

    def __init__(self, message: str | None = None, details: list[dict] | None = None):
        self.message = message or self.default_message
        self.details = details or []
        super().__init__(self.message)


class InvalidOrderTransition(StockFlowDomainError):
    code = "INVALID_ORDER_TRANSITION"
    default_message = "The requested order transition is not allowed."


class InsufficientStock(StockFlowDomainError):
    code = "INSUFFICIENT_STOCK"
    default_message = "One or more order items do not have enough available stock."


class InactiveProduct(StockFlowDomainError):
    code = "INACTIVE_PRODUCT"
    default_message = "One or more order items reference an inactive product."


class InactiveWarehouse(StockFlowDomainError):
    code = "INACTIVE_WAREHOUSE"
    default_message = "One or more order items reference an inactive warehouse."


class InventoryNotFound(StockFlowDomainError):
    code = "INVENTORY_NOT_FOUND"
    default_message = "One or more order items do not have an inventory record."


class InvalidOrderItemQuantity(StockFlowDomainError):
    code = "INVALID_ORDER_ITEM_QUANTITY"
    default_message = "Order item quantities must be positive."


class InvalidCancellationSource(StockFlowDomainError):
    code = "INVALID_CANCELLATION_SOURCE"
    default_message = "Cancellation source must be manual or expiration."


class InvalidInventoryState(StockFlowDomainError):
    code = "INVALID_INVENTORY_STATE"
    default_message = "Inventory quantities are not valid for this order transition."


class DuplicateOrderItem(StockFlowDomainError):
    code = "DUPLICATE_ORDER_ITEM"
    default_message = "The same product and warehouse cannot appear twice in one order."
