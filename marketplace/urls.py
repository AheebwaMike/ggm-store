from django.urls import path
from . import views

urlpatterns = [
    path('sw.js', views.service_worker, name='service_worker'),
    path('', views.home, name='home'),
    path('group/<int:group_id>/', views.product_list, name='product_list'),
    path('cart/', views.cart_view, name='cart_view'),
    path('cart/count/', views.cart_count, name='cart_count'),
    path('cart/add/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/update/<int:product_id>/', views.cart_update, name='cart_update'),
    path('checkout/', views.checkout, name='checkout'),
    path('order/success/<int:order_id>/', views.order_success, name='order_success'),
    path('my-orders/', views.customer_orders, name='customer_orders'),
    path('my-orders/<int:order_id>/', views.customer_order_detail, name='customer_order_detail'),
    path('staff/', views.staff_orders, name='staff_orders'),
    path('staff/order/<int:order_id>/', views.staff_order_detail, name='staff_order_detail'),
    path('staff/order/<int:order_id>/action/', views.staff_order_action, name='staff_order_action'),
    path('staff/order/<int:order_id>/slip/', views.staff_order_slip, name='staff_order_slip'),
    path('staff/stock/', views.staff_stock, name='staff_stock'),
    path('staff/stock/<int:product_id>/toggle/', views.staff_toggle_stock, name='staff_toggle_stock'),
    path('owner/', views.owner_dashboard, name='owner_dashboard'),
]