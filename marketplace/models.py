# marketplace/models.py
from django.db import models

class ProductGroup(models.Model):
    name = models.CharField(max_length=255, unique=True)
    
    def __str__(self):
        return self.name

class Unit(models.Model):
    name = models.CharField(max_length=50, unique=True) # e.g., PCS, KG, CARTON
    
    def __str__(self):
        return self.name

class Product(models.Model):
    code = models.CharField(max_length=50, unique=True) # e.g., "000001"
    name = models.CharField(max_length=255)
    group = models.ForeignKey(ProductGroup, on_delete=models.SET_NULL, null=True, blank=True)
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True)
    
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    stock_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    manually_disabled = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True) # Toggle to hide out-of-stock or disabled items
    image = models.ImageField(upload_to='products/', null=True, blank=True)
    
    def __str__(self):
        return f"{self.code} - {self.name}"

class Apartment(models.Model):
    name = models.CharField(max_length=255, unique=True) # e.g., "Block B"
    delivery_fee_override = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Leave blank to use the global delivery fee. Set to 0 for free delivery.",
    )
    
    def __str__(self):
        return self.name


class StoreConfig(models.Model):
    delivery_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=2000.00,
        help_text="Standard delivery fee",
    )
    free_delivery_threshold = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=35000.00,
        help_text="Order amount for free delivery",
    )
    minimum_order_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Minimum cart total to allow checkout (0 means no limit)",
    )

    class Meta:
        verbose_name = "Store Configuration"
        verbose_name_plural = "Store Configuration"

    def __str__(self):
        return "Store Configuration"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class Customer(models.Model):
    phone_number = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=255, blank=True)
    apartment = models.ForeignKey(Apartment, on_delete=models.SET_NULL, null=True, blank=True)
    unit_number = models.CharField(max_length=50, blank=True) # e.g., "Apt 4"
    
    def __str__(self):
        return f"{self.name} ({self.phone_number})"

class Order(models.Model):
    STATUS_CHOICES = [
        ('new', 'New Order'),
        ('confirmed', 'Confirmed'),
        ('packed', 'Packed & Ready'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]
    PAYMENT_CHOICES = [
        ('cash', 'Cash on Delivery'),
        ('momo', 'MoMo on Delivery'),
    ]
    
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='cash')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    note = models.TextField(blank=True, help_text="Customer delivery instructions")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Order #{self.id} - {self.customer.name}"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1.00)
    price_at_time_of_order = models.DecimalField(max_digits=10, decimal_places=2) # Lock in the price
    
    def __str__(self):
        return f"{self.quantity} x {self.product.name}"


class FeaturedCampaign(models.Model):
    name = models.CharField(
        max_length=255,
        help_text="Internal name for this campaign (e.g., 'Weekend Sugar Promo')",
    )
    products = models.ManyToManyField(Product, related_name='featured_in')
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    is_active = models.BooleanField(
        default=True,
        help_text="Uncheck to kill this campaign early",
    )

    def __str__(self):
        return self.name
    