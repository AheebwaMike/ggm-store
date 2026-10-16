# marketplace/admin.py
from django.contrib import admin
from .models import ProductGroup, Unit, Product, Apartment, Customer, Order, OrderItem

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
    list_display = ('code', 'name', 'group', 'unit', 'selling_price', 'stock_quantity', 'is_active')
    list_filter = ('is_active', 'group', 'unit')
    search_fields = ('code', 'name')

@admin.register(Apartment)
class ApartmentAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

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
    list_display = ('id', 'customer', 'status', 'payment_method', 'total_amount', 'created_at')
    list_filter = ('status', 'payment_method', 'created_at')
    search_fields = ('id', 'customer__name', 'customer__phone_number')
    inlines = [OrderItemInline]