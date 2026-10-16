from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('group/<int:group_id>/', views.product_list, name='product_list'),
]