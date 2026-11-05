"""Home page and the pages around it: shelves, discover grid, all categories, card quantity stepper."""
import json

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .models import Customer, FeaturedCampaign, Product, Shelf
from .shelves import (
    OVERFETCH, _units_sold, build_items, categories_with_counts, discover_page, get_config, home_categories,
    home_shelves, loose_products, sellable_products, seed_default_shelves, shelf_queryset,
)

SEARCH_LIMIT = 50
SHELF_PAGE_LIMIT = 120
MAX_DISCOVER_PAGE = 20
POPULAR_SEARCHES = ['milk', 'sugar', 'rice', 'eggs', 'bread', 'soap', 'cooking oil']


@ensure_csrf_cookie
def home(request):
    config = get_config()
    query = request.GET.get('q', '').strip()

    if query:
        rows = list(
            loose_products()
            .filter(Q(name__icontains=query) | Q(code__icontains=query))
            .order_by('name')[:SEARCH_LIMIT]
        )
        return render(request, 'marketplace/home.html', {
            'config': config,
            'query': query,
            'search_results': build_items(rows, loose_products(), SEARCH_LIMIT),
        })

    seed_default_shelves(config)

    now = timezone.now()
    active_campaigns = FeaturedCampaign.objects.filter(is_active=True, starts_at__lte=now, ends_at__gte=now)
    featured_products = list(
        Product.objects.filter(featured_in__in=active_campaigns, is_active=True, selling_price__gt=0)
        .select_related('unit').distinct()[:12]
    )

    current_customer = None
    customer_id = request.session.get('customer_id')
    if customer_id:
        try:
            current_customer = Customer.objects.get(id=customer_id)
        except (Customer.DoesNotExist, ValueError, TypeError):
            request.session.pop('customer_id', None)

    frequent_products = []
    if current_customer:
        frequent_products = list(
            Product.objects.filter(orderitem__order__customer=current_customer, is_active=True, selling_price__gt=0)
            .select_related('unit').annotate(times_ordered=Count('orderitem')).order_by('-times_ordered')[:8]
        )

    discover_items, has_more = discover_page(config, 1)
    category_count = len(categories_with_counts())

    return render(request, 'marketplace/home.html', {
        'config': config,
        'query': '',
        'current_customer': current_customer,
        'popular_searches': POPULAR_SEARCHES,
        'pinned_groups': home_categories(),
        'category_count': category_count,
        'frequent_products': frequent_products,
        'featured_products': featured_products,
        'shelves': home_shelves(config),
        'discover_items': discover_items,
        'discover_has_more': has_more,
        'discover_next_page': 2,
    })


def discover(request):
    """HTMX: the next page of the 'Discover more' grid."""
    try:
        page = int(request.GET.get('page', '1'))
    except ValueError:
        page = 1
    page = max(1, min(page, MAX_DISCOVER_PAGE))
    items, has_more = discover_page(get_config(), page)
    return render(request, 'marketplace/_discover_page.html', {
        'discover_items': items,
        'discover_has_more': has_more,
        'discover_next_page': page + 1,
    })


def all_categories(request):
    return render(request, 'marketplace/all_categories.html', {'groups': categories_with_counts()})


def shelf_detail(request, shelf_id):
    """The 'See all' page of a shelf."""
    shelf = get_object_or_404(Shelf, pk=shelf_id, is_active=True)
    config = get_config()
    rows = list(shelf_queryset(shelf, config)[: SHELF_PAGE_LIMIT * OVERFETCH])
    return render(request, 'marketplace/shelf_detail.html', {
        'shelf': shelf,
        'items': build_items(rows, sellable_products(), SHELF_PAGE_LIMIT),
    })


# ---------------------------------------------------------------- quantity stepper on product cards

def _toast_response(status, message, kind='error'):
    response = HttpResponse(message, status=status)
    response['HX-Trigger'] = json.dumps({'ggmToast': {'message': message, 'kind': kind}})
    return response


@require_POST
def card_qty(request, product_id):
    """Change one product's quantity from its card and return the card's button or stepper."""
    action = request.POST.get('action', 'inc')
    product = get_object_or_404(Product, id=product_id, is_active=True)

    cart = request.session.get('cart', {})
    key = str(product.id)
    quantity = int(cart.get(key, 0))
    first_add = False

    if action == 'inc':
        if not get_config().is_open:
            return _toast_response(403, 'The store is closed right now')
        stock = product.stock_quantity or 0
        if product.manually_disabled or stock <= 0:
            return _toast_response(409, 'Sorry, that item is out of stock')
        if quantity + 1 > stock:
            return _toast_response(409, f'Only {stock:.0f} left in stock')
        quantity += 1
        first_add = quantity == 1
    elif action == 'dec':
        quantity = max(0, quantity - 1)

    if quantity > 0:
        cart[key] = quantity
    else:
        cart.pop(key, None)
    request.session['cart'] = cart
    request.session.modified = True

    response = render(request, 'marketplace/_card_control.html', {'product': product, 'qty': quantity})
    triggers = {'cartUpdated': ''}
    if first_add:
        triggers['ggmToast'] = {'message': f'Added: {product.name}'}
    response['HX-Trigger'] = json.dumps(triggers)
    return response


# ---------------------------------------------------------------- staff: photo to-do list

@login_required
def staff_photo_todo(request):
    """Products still without a photo, the best sellers first, so photographing starts where it matters."""
    active = Product.objects.filter(is_active=True, selling_price__gt=0)
    without_photo = active.filter(Q(image='') | Q(image__isnull=True))
    products = list(
        without_photo.select_related('group').annotate(sold=_units_sold()).order_by('-sold', 'name')[:100]
    )
    total = active.count()
    missing = without_photo.count()
    return render(request, 'marketplace/staff_photo_todo.html', {
        'products': products,
        'total': total,
        'missing': missing,
        'with_photo': total - missing,
        'config': get_config(),
    })