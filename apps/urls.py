from rest_framework.routers import DefaultRouter

from apps.inventory.views import InventoryViewSet
from apps.orders.views import OrderViewSet
from apps.products.views import ProductViewSet, WarehouseViewSet


router = DefaultRouter()
router.register("products", ProductViewSet, basename="product")
router.register("warehouses", WarehouseViewSet, basename="warehouse")
router.register("inventory", InventoryViewSet, basename="inventory")
router.register("orders", OrderViewSet, basename="order")

urlpatterns = router.urls
