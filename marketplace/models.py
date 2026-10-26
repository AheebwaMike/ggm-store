from django.db import models

from marketplace.storage import CloudinaryMediaStorage

class ProductGroup(models.Model):
    name = models.CharField(max_length=255, unique=True)
    
    def __str__(self):
        return self.name

class Unit(models.Model):
    name = models.CharField(max_length=50, unique=True) # e.g., PCS, KG, CARTON
    
    def __str__(self):
        return self.name

class Product(models.Model):
    code = models.CharField(max_length=50, unique=True, db_index=True) # e.g., "000001"
    name = models.CharField(max_length=255)
    parent_group = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        help_text="Items with the same parent group will be grouped together (e.g., 'Kakira Sugar')",
    )
    variant_label = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="The specific variant shown to the customer (e.g., '1KG', '25KG', 'Chilli')",
    )
    group = models.ForeignKey(ProductGroup, on_delete=models.SET_NULL, null=True, blank=True)
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True)
    
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    stock_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    low_stock_threshold = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=5.00,
        help_text="Alert when stock falls to or below this number",
    )
    manually_disabled = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True) # Toggle to hide out-of-stock or disabled items
    image = models.ImageField(
        upload_to='products/',
        null=True,
        blank=True,
        storage=CloudinaryMediaStorage(),
    )

    @property
    def thumbnail_url(self):
        if self.image:
            return self.image.url
        return None
    
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
    is_open = models.BooleanField(
        default=True,
        help_text="Toggle to stop accepting new orders",
    )
    closed_message = models.CharField(
        max_length=255,
        default="We are currently closed. Please check back later or order via WhatsApp.",
        help_text="Message shown to customers when closed",
    )
    whatsapp_number = models.CharField(
        max_length=20,
        blank=True,
        help_text="Store WhatsApp number (e.g., 256770000000) without '+' or spaces",
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
    phone_number = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=255, blank=True)
    apartment = models.ForeignKey(Apartment, on_delete=models.SET_NULL, null=True, blank=True)
    unit_number = models.CharField(max_length=50, blank=True) # e.g., "Apt 4"
    
    def __str__(self):
        return f"{self.name} ({self.phone_number})"


class PushSubscription(models.Model):
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='push_subscriptions',
    )
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        customer_name = self.customer.name if self.customer else 'Anonymous'
        return f"Subscription for {customer_name} ({self.endpoint[:30]}...)"


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
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new', db_index=True)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='cash')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    is_modified = models.BooleanField(default=False, help_text="True if staff altered the items after the customer placed it")
    note = models.TextField(blank=True, help_text="Customer delivery instructions")
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']

    @property
    def subtotal(self):
        return sum(
            (item.quantity * item.price_at_time_of_order) for item in self.items.all()
        )

    def __str__(self):
        return f"Order #{self.id} - {self.customer.name}"


class WhatsAppNotificationLog(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='wa_logs')
    status_sent = models.CharField(max_length=20)
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"WhatsApp for Order #{self.order.id} ({self.status_sent})"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items', db_index=True)
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
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField(db_index=True)
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Uncheck to kill this campaign early",
    )

    def __str__(self):
        return self.name
    