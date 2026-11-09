# marketplace/admin.py
from django.contrib import admin
from django.db.models import Q
from django.urls import reverse
from django.utils.html import format_html
from .shelves import MIN_SHELF_ITEMS, get_config, shelf_items
from .models import (
    Apartment,
    Customer,
    Family,
    FamilyDismissal,
    FeaturedCampaign,
    Order,
    OrderItem,
    Product,
    ProductBulkOption,
    ProductGroup,
    PushSubscription,
    QRScan,
    Shelf,
    ShelfItem,
    StoreConfig,
    Unit,
    WhatsAppNotificationLog,
    CategoryMerge,
)

@admin.register(ProductGroup)
class ProductGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'home_order')
    list_editable = ('home_order',)
    search_fields = ('name',)
    ordering = ('name',)


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

class HasPhotoFilter(admin.SimpleListFilter):
    title = 'photo'
    parameter_name = 'has_photo'

    def lookups(self, request, model_admin):
        return (('yes', 'Has a photo'), ('no', 'No photo yet'))

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.exclude(image='').exclude(image__isnull=True)
        if self.value() == 'no':
            return queryset.filter(Q(image='') | Q(image__isnull=True))
        return queryset


class ProductBulkOptionInline(admin.TabularInline):
    model = ProductBulkOption
    extra = 1
    fields = ('label', 'pieces_per_pack', 'price', 'image', 'is_active', 'position')
    ordering = ('position', 'id')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'code',
        'name',
        'parent_group',
        'variant_label',
        'variant_kind',
        'group',
        'unit',
        'selling_price',
        'stock_quantity',
        'low_stock_threshold',
        'is_active',
        'image_preview',
    )
    list_editable = ('parent_group', 'variant_label', 'variant_kind')
    list_filter = (HasPhotoFilter, 'is_active', 'group', 'unit', 'parent_group', 'low_stock_threshold')
    search_fields = ('code', 'name', 'parent_group')
    readonly_fields = ('image_preview',)
    inlines = [ProductBulkOptionInline]

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="width: 50px; height: 50px; object-fit: cover; border-radius: 4px;" />',
                obj.image.url,
            )
        return "No Image"


@admin.register(Family)
class FamilyAdmin(admin.ModelAdmin):
    list_display = ('name', 'has_cover', 'created_at')
    search_fields = ('name',)
    readonly_fields = ('created_at',)

    @admin.display(boolean=True, description='Cover set')
    def has_cover(self, obj):
        return bool(obj.cover_image)


@admin.register(Apartment)
class ApartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_served', 'delivery_fee_override', 'qr_poster')
    list_filter = ('is_served',)
    search_fields = ('name', 'slug')
    fields = ('name', 'slug', 'is_served', 'welcome_message', 'delivery_fee_override')

    def get_readonly_fields(self, request, obj=None):
        # Once a slug exists it is printed on QR codes, so protect it from accidental edits.
        return ('slug',) if obj and obj.slug else ()

    @admin.display(description='QR')
    def qr_poster(self, obj):
        if not obj.pk:
            return ''
        return format_html('<a href="{}" target="_blank">Poster</a>', reverse('staff_qr_poster', args=[obj.pk]))


@admin.register(QRScan)
class QRScanAdmin(admin.ModelAdmin):
    list_display = ('apartment', 'source', 'scanned_at')
    list_filter = ('apartment', 'source')
    date_hierarchy = 'scanned_at'
    readonly_fields = ('apartment', 'source', 'visitor', 'scanned_at')

    def has_add_permission(self, request):
        return False


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
    list_display = ('id', 'customer', 'status', 'payment_method', 'total_amount', 'delivery_fee', 'qr_apartment', 'created_at')
    list_filter = ('status', 'payment_method', 'qr_apartment', 'created_at')
    search_fields = ('id', 'customer__name', 'customer__phone_number')
    readonly_fields = ('confirmed_at', 'packed_at', 'delivered_at', 'qr_apartment', 'qr_source')
    inlines = [OrderItemInline]


@admin.register(WhatsAppNotificationLog)
class WhatsAppNotificationLogAdmin(admin.ModelAdmin):
    list_display = ('order', 'status_sent', 'sent_at')
    list_filter = ('status_sent', 'sent_at')
    search_fields = ('order__id', 'order__customer__phone_number')
    readonly_fields = ('order', 'status_sent', 'sent_at')


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'customer', 'created_at')


@admin.register(FeaturedCampaign)
class FeaturedCampaignAdmin(admin.ModelAdmin):
    list_display = ('name', 'starts_at', 'ends_at', 'is_active')
    list_filter = ('is_active', 'starts_at', 'ends_at')
    filter_horizontal = ('products',)


class ShelfItemInline(admin.TabularInline):
    model = ShelfItem
    extra = 3
    autocomplete_fields = ('product',)
    fields = ('product', 'position')


@admin.register(Shelf)
class ShelfAdmin(admin.ModelAdmin):
    list_display = ('title', 'kind', 'position', 'is_active', 'on_home_page')
    list_editable = ('position', 'is_active')
    list_filter = ('kind', 'is_active')
    inlines = [ShelfItemInline]
    fieldsets = (
        (None, {'fields': ('title', 'kind', 'position', 'max_items', 'is_active')}),
        ('Only for some kinds', {
            'fields': ('group', 'max_price'),
            'description': "Pick a category for 'Best sellers from one product category'. "
                           "Enter a price for 'Products under a price'. "
                           "For hand-picked shelves, add the products in the table below.",
        }),
    )

    @admin.display(description='On the home page now?')
    def on_home_page(self, obj):
        if not obj.is_active:
            return 'Hidden (switched off)'
        count = len(shelf_items(obj, get_config()))
        if count >= MIN_SHELF_ITEMS:
            return f'Yes, {count} products'
        return f'No, only {count} usable products (needs {MIN_SHELF_ITEMS})'


@admin.register(FamilyDismissal)
class FamilyDismissalAdmin(admin.ModelAdmin):
    """Delete a dismissal to show that family suggestion again."""
    list_display = ('key', 'created_at')
    search_fields = ('key',)
    readonly_fields = ('key', 'created_at')

    def has_add_permission(self, request):
        return False


@admin.register(CategoryMerge)
class CategoryMergeAdmin(admin.ModelAdmin):
    list_display = ('target_name', 'products_moved', 'created_at', 'undone_at')
    readonly_fields = ('target', 'target_name', 'target_was_created', 'target_home_order_before',
                       'moves', 'products_moved', 'created_at', 'undone_at')

    def has_add_permission(self, request):
        return False
