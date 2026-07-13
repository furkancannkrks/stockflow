from django.urls import path

from apps.products.browser_views import (
    ProductCreateView,
    ProductDetailView,
    ProductListView,
    ProductUpdateView,
)


app_name = "products"

urlpatterns = [
    path("", ProductListView.as_view(), name="product-list"),
    path("new/", ProductCreateView.as_view(), name="product-create"),
    path("<int:pk>/", ProductDetailView.as_view(), name="product-detail"),
    path("<int:pk>/edit/", ProductUpdateView.as_view(), name="product-update"),
]
