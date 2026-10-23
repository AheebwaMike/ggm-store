# marketplace/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Apartment,
    Customer,
    FeaturedCampaign,
    Order,
    OrderItem,
    Product,
    ProductGroup,
    StoreConfig,
    Unit,
    WhatsAppNotificationLog,
)

@admin.register(ProductGroup)
class ProductGroupAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'code',
        'name',
        'group',
        'unit',
        'selling_price',
        'stock_quantity',
        'low_stock_threshold',
        'is_active',
        'image_preview',
    )
    list_filter = ('is_active', 'group', 'unit', 'low_stock_threshold')
    search_fields = ('code', 'name')
    readonly_fields = ('image_preview',)

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="width: 50px; height: 50px; object-fit: cover; border-radius: 4px;" />',
                obj.image.url,
            )
        return "No Image"

@admin.register(Apartment)
class ApartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'delivery_fee_override')
    search_fields = ('name',)


@admin.register(StoreConfig)
class StoreConfigAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not StoreConfig.objects.exists()


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone_number', 'apartment', 'unit_number')
    search_fields = ('name', 'phone_number')

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('price_at_time_of_order',)

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'status', 'payment_method', 'total_amount', 'delivery_fee', 'created_at')
    list_filter = ('status', 'payment_method', 'created_at')
    search_fields = ('id', 'customer__name', 'customer__phone_number')
    inlines = [OrderItemInline]


@admin.register(WhatsAppNotificationLog)
class WhatsAppNotificationLogAdmin(admin.ModelAdmin):
    list_display = ('order', 'status_sent', 'sent_at')
    list_filter = ('status_sent', 'sent_at')
    search_fields = ('order__id', 'order__customer__phone_number')
    readonly_fields = ('order', 'status_sent', 'sent_at')


@admin.register(FeaturedCampaign)
class FeaturedCampaignAdmin(admin.ModelAdmin):
    list_display = ('name', 'starts_at', 'ends_at', 'is_active')
    list_filter = ('is_active', 'starts_at', 'ends_at')
    filter_horizontal = ('products',)