from django.urls import path
from . import views

app_name = 'products'

urlpatterns = [
    path('api/products/', views.api_add_product, name='api_add_product'),
    path('products/', views.products_search, name='products_search'),
]
