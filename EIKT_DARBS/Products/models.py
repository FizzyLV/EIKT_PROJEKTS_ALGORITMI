from django.db import models


class Product(models.Model):
    company = models.CharField(max_length=255)
    category = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    name_normalized = models.CharField(max_length=255)
    description = models.TextField()
    description_normalized = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    available = models.BooleanField(default=True)
    rating = models.DecimalField(max_digits=3, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
