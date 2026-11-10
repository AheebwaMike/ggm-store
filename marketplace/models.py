"""
Marketplace models for products, orders, customers, and related entities.
"""

from django.db import models
from django.utils.text import slugify
from django.utils import timezone

from marketplace.storage import CloudinaryMediaStorage

class ProductGroup(models.Model):
    name = models.CharField(max_length=255, unique=True)
    image = models.ImageField(
        upload_to='product_groups/',
        null=True,
        blank=True,
        storage=CloudinaryMediaStorage(),
    )
    home_order = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Give a number (1 = first) to show this category in the row at the top of the home page. "
                  "Leave blank to keep it off that row.",
    )

    @property
    def thumbnail_url(self):
        """Small version of the category picture (about 160x160) for the category row."""
        if not self.image:
            return None
        storage = self.image.storage
        if hasattr(storage, 'transformed_url'):
            return storage.transformed_url(
                self.image.name, width=160, height=160, crop='fill', gravity='auto',
            )
        return self.image.url
    
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
    variant_kind = models.CharField(
        max_length=10,
        blank=True,
        choices=[('size', 'Sizes'), ('flavour', 'Flavours'), ('pack', 'Packs'), ('type', 'Types')],
        help_text="Optional. Used on the card, for example '3 flavours'. Leave blank to guess from the labels.",
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
    created_at = models.DateTimeField(auto_now_add=True, null=True, editable=False)


    @property
    def thumbnail_url(self):
        """Small, compressed image for cards, grids and the cart (about 300x300)."""
        if not self.image:
            return None
        storage = self.image.storage
        if hasattr(storage, 'transformed_url'):
            return storage.transformed_url(
                self.image.name, width=300, height=300, crop='pad', background='auto',
            )
        return self.image.url
    
    def __str__(self):
        return f"{self.code} - {self.name}"


class ProductBulkOption(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='bulk_options')
    label = models.CharField(max_length=50, help_text="Shown to the customer, e.g. 'Carton of 12'")
    pieces_per_pack = models.PositiveIntegerField(
        help_text="How many single units are in one pack (e.g. 12 for a carton)",
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Fixed price for the whole pack. Not computed from the single-unit price.",
    )
    image = models.ImageField(
        upload_to='bulk_options/',
        null=True,
        blank=True,
        storage=CloudinaryMediaStorage(),
    )
    is_active = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=100, help_text="Smaller numbers appear first")

    class Meta:
        ordering = ['position', 'id']
        constraints = [
            models.UniqueConstraint(fields=['product', 'label'], name='unique_bulk_label_per_product'),
        ]

    def __str__(self):
        return f"{self.product.name} — {self.label}"


class Family(models.Model):
    """A variant family's metadata. Linked to Product.parent_group by name (not by FK)."""
    name = models.CharField(max_length=255, unique=True, db_index=True)
    cover_image = models.ImageField(
        upload_to='families/',
        null=True,
        blank=True,
        storage=CloudinaryMediaStorage(),
        help_text="Poster shot shown on the product card. Falls back to the first variant's photo if empty.",
    )
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Families'
        ordering = ['name']

    def __str__(self):
        return self.name


class FamilyDismissal(models.Model):
    """A suggested family staff marked as not a family, so it is not suggested again."""
    key = models.CharField(max_length=300, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.key


class Shelf(models.Model):
    """A row of products on the home page."""
    CURATED = 'curated'
    CATEGORY = 'category'
    NEW = 'new'
    UNDER_PRICE = 'under_price'
    POPULAR = 'popular'
    KIND_CHOICES = [
        (CURATED, 'Hand-picked products (you choose them below)'),
        (CATEGORY, 'Best sellers from one product category'),
        (NEW, 'New arrivals (added in the last 14 days)'),
        (UNDER_PRICE, 'Products under a price'),
        (POPULAR, 'Popular right now (sold in the last 14 days)'),
    ]

    title = models.CharField(max_length=80)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=CURATED)
    group = models.ForeignKey(
        ProductGroup, on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Only for 'Best sellers from one product category'",
    )
    max_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Only for 'Products under a price'",
    )
    max_items = models.PositiveSmallIntegerField(default=12, help_text="How many products to show in the row")
    position = models.PositiveSmallIntegerField(default=100, help_text="Smaller numbers appear higher on the home page")
    is_active = models.BooleanField(default=True, help_text="Untick to hide this shelf")

    class Meta:
        ordering = ['position', 'id']
        verbose_name_plural = 'Shelves'

    def __str__(self):
        return self.title


class CategoryMerge(models.Model):
    """A record of one "merge categories" action, so it can be undone."""
    created_at = models.DateTimeField(auto_now_add=True)
    target = models.ForeignKey(ProductGroup, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    target_name = models.CharField(max_length=255)
    target_was_created = models.BooleanField(default=False)
    target_home_order_before = models.PositiveSmallIntegerField(null=True, blank=True)
    # [{"source_id": 3, "source_name": "Tea", "home_order": 2, "product_ids": [..], "shelf_ids": [..]}, ...]
    moves = models.JSONField(default=list)
    products_moved = models.PositiveIntegerField(default=0)
    undone_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.products_moved} products into {self.target_name}'

class ShelfItem(models.Model):
    """A product on a hand-picked shelf, in the order you want."""
    shelf = models.ForeignKey(Shelf, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    position = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ['position', 'id']
        constraints = [
            models.UniqueConstraint(fields=['shelf', 'product'], name='unique_product_per_shelf'),
        ]

    def __str__(self):
        return f'{self.shelf} / {self.product}'
    

class Apartment(models.Model):
    name = models.CharField(max_length=255, unique=True) # e.g., "Block B"
    slug = models.SlugField(
        max_length=60,
        unique=True,
        null=True,
        blank=True,
        help_text="Used in this apartment's QR link (/a/<slug>/). Created automatically. "
                  "Do not change it once QR codes are printed.",
    )
    is_served = models.BooleanField(
        default=True,
        help_text="Untick if you do not deliver here yet. Scans of its QR code are still counted.",
    )
    welcome_message = models.CharField(
        max_length=160,
        blank=True,
        help_text="Optional line shown to people who arrive by this apartment's QR code.",
    )
    delivery_fee_override = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Leave blank to use the global delivery fee. Set to 0 for free delivery.",
    )

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._make_unique_slug()
        super().save(*args, **kwargs)

    def _make_unique_slug(self):
        base = slugify(self.name)[:50] or 'apartment'
        slug, number = base, 2
        while Apartment.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f'{base}-{number}'
            number += 1
        return slug


class QRScan(models.Model):
    """One scan of an apartment's QR code (the same phone at the same code counts once per 30 min)."""
    apartment = models.ForeignKey(Apartment, on_delete=models.CASCADE, related_name='scans')
    source = models.CharField(max_length=40, blank=True, help_text="Placement tag, e.g. gate or corridor")
    visitor = models.CharField(max_length=32, blank=True, db_index=True)
    scanned_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-scanned_at']

    def __str__(self):
        return f"{self.apartment} scan at {self.scanned_at:%Y-%m-%d %H:%M}"


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
    ghost_stock_enabled = models.BooleanField(
        default=True,
        help_text="When ON, customers can buy any quantity regardless of stock. "
                  "When OFF, the cart and checkout respect each product's stock_quantity.",
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
    shelves_require_photo = models.BooleanField(
        default=True,
        help_text="Home page shelves only show products that have a photo. "
                  "Untick while you are still photographing products.",
    )
    shelves_seeded = models.BooleanField(default=False, editable=False)

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

    # When each stage was reached (filled in automatically by save(); blank on older orders)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    packed_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    # Which apartment QR code the customer's visit started from, if any
    qr_apartment = models.ForeignKey(
        'Apartment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='qr_orders',
    )
    qr_source = models.CharField(max_length=40, blank=True, help_text="Placement tag of that QR code, e.g. gate")
    
    class Meta:
        ordering = ['-created_at']

    _STAGE_FIELDS = {
        'confirmed': 'confirmed_at',
        'packed': 'packed_at',
        'delivered': 'delivered_at',
    }

    def save(self, *args, **kwargs):
        # Record the first time an order reaches a stage, whoever changed it (staff page or admin).
        field = self._STAGE_FIELDS.get(self.status)
        if field and getattr(self, field) is None:
            setattr(self, field, timezone.now())
            update_fields = kwargs.get('update_fields')
            if update_fields is not None:
                kwargs['update_fields'] = list(update_fields) + [field]
        super().save(*args, **kwargs)

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
    bulk_option = models.ForeignKey(
        ProductBulkOption,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='order_items',
    )
    bulk_label = models.CharField(max_length=50, blank=True)
    pieces_per_pack = models.PositiveIntegerField(default=1)
    
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
    