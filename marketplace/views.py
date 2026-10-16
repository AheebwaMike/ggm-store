from django.shortcuts import render, get_object_or_404
from .models import ProductGroup, Product


def home(request):
    groups = ProductGroup.objects.all().order_by('name')
    return render(request, 'marketplace/home.html', {'groups': groups})


def product_list(request, group_id):
    group = get_object_or_404(ProductGroup, id=group_id)
    # Only show products that are active (auto-hidden if out of stock or disabled)
    products = Product.objects.filter(
        group=group, is_active=True, selling_price__gt=0
    ).order_by('name')
    return render(request, 'marketplace/product_list.html', {
        'group': group,
        'products': products,
    })