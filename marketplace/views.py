import json

from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from .models import ProductGroup, Product, Apartment, Customer, Order, OrderItem


# ---------- Cart helpers ----------

def _get_cart(request):
    """Return session cart. Format: { 'product_id_str': quantity_int }"""
    return request.session.get('cart', {})


def _save_cart(request, cart):
    request.session['cart'] = cart
    request.session.modified = True


def _cart_total_items(cart):
    return sum(int(q) for q in cart.values())


# ---------- Views ----------
@ensure_csrf_cookie
def home(request):
    groups = ProductGroup.objects.all().order_by('name')
    return render(request, 'marketplace/home.html', {'groups': groups})


def product_list(request, group_id):
    group = get_object_or_404(ProductGroup, id=group_id)
    products = Product.objects.filter(
        group=group, is_active=True, selling_price__gt=0
    ).order_by('name')
    return render(request, 'marketplace/product_list.html', {
        'group': group,
        'products': products,
    })


def cart_count(request):
    """Returns just the total quantity in cart (as plain text)."""
    cart = _get_cart(request)
    return HttpResponse(str(_cart_total_items(cart)))


@require_POST
def add_to_cart(request, product_id):
    """Add one unit of the product to the cart. Responds with new count + HTMX trigger."""
    product = get_object_or_404(Product, id=product_id, is_active=True)
    cart = _get_cart(request)
    key = str(product.id)
    cart[key] = int(cart.get(key, 0)) + 1
    _save_cart(request, cart)

    total = _cart_total_items(cart)
    response = HttpResponse(str(total))
    response['HX-Trigger'] = 'cartUpdated'  # Fires event that navbar listens for
    return response


# ---------- Cart page + updates ----------

def _cart_details(request):
    """Build enriched cart data for templates: list of items + subtotal."""
    cart = _get_cart(request)
    items = []
    subtotal = 0
    for pid_str, qty in cart.items():
        try:
            product = Product.objects.get(id=int(pid_str), is_active=True)
        except Product.DoesNotExist:
            continue
        line_total = product.selling_price * int(qty)
        subtotal += line_total
        items.append({
            'product': product,
            'quantity': int(qty),
            'line_total': line_total,
        })
    return items, subtotal


def cart_view(request):
    items, subtotal = _cart_details(request)
    return render(request, 'marketplace/cart.html', {'items': items, 'subtotal': subtotal})


@require_POST
def cart_update(request, product_id):
    action = request.POST.get('action', 'inc')
    cart = _get_cart(request)
    key = str(product_id)

    if key in cart:
        if action == 'inc':
            cart[key] = int(cart[key]) + 1
        elif action == 'dec':
            cart[key] = int(cart[key]) - 1
            if cart[key] <= 0:
                del cart[key]
        elif action == 'remove':
            del cart[key]

    _save_cart(request, cart)

    items, subtotal = _cart_details(request)
    response = render(request, 'marketplace/_cart_body.html', {'items': items, 'subtotal': subtotal})
    response['HX-Trigger'] = 'cartUpdated'
    return response


def checkout(request):
    items, subtotal = _cart_details(request)
    if not items:
        messages.warning(request, 'Your cart is empty.')
        return redirect('home')

    apartments = Apartment.objects.all().order_by('name')
    if request.method == 'POST':
        phone = request.POST.get('phone', '').strip()
        name = request.POST.get('name', '').strip()
        apartment_id = request.POST.get('apartment', '').strip()
        unit_number = request.POST.get('unit_number', '').strip()
        payment_method = request.POST.get('payment_method', '').strip()

        apartment = None
        if not phone:
            messages.error(request, 'Please enter your phone number.')
        if not apartment_id:
            messages.error(request, 'Please select your apartment.')
        else:
            try:
                apartment = Apartment.objects.get(pk=apartment_id)
            except (Apartment.DoesNotExist, ValueError, TypeError):
                messages.error(request, 'Please select a valid apartment.')
        if payment_method not in {'cash', 'momo'}:
            messages.error(request, 'Please select a valid payment method.')

        if not phone or apartment is None or payment_method not in {'cash', 'momo'}:
            return render(request, 'marketplace/checkout.html', {
                'items': items,
                'subtotal': subtotal,
                'apartments': apartments,
                'form_data': request.POST,
                'item_count': sum(item['quantity'] for item in items),
            })

        with transaction.atomic():
            customer, _ = Customer.objects.update_or_create(
                phone_number=phone,
                defaults={
                    'name': name,
                    'apartment': apartment,
                    'unit_number': unit_number,
                },
            )
            order = Order.objects.create(
                customer=customer,
                status='new',
                payment_method=payment_method,
                total_amount=subtotal,
            )
            for item in items:
                OrderItem.objects.create(
                    order=order,
                    product=item['product'],
                    quantity=item['quantity'],
                    price_at_time_of_order=item['product'].selling_price,
                )

            request.session['cart'] = {}
            request.session.modified = True

        return redirect('order_success', order_id=order.id)

    return render(request, 'marketplace/checkout.html', {
        'items': items,
        'subtotal': subtotal,
        'apartments': apartments,
        'form_data': {},
        'item_count': sum(item['quantity'] for item in items),
    })


def order_success(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    return render(request, 'marketplace/order_success.html', {'order': order})


@login_required
def staff_orders(request):
    status = request.GET.get('status', 'new')
    valid_statuses = {'new', 'confirmed', 'packed', 'delivered', 'all'}
    if status not in valid_statuses:
        status = 'new'

    orders = Order.objects.select_related(
        'customer', 'customer__apartment'
    ).prefetch_related('items__product')
    if status != 'all':
        orders = orders.filter(status=status)
    orders = orders.order_by('-created_at')

    context = {
        'status': status,
        'orders': orders,
        'new_count': Order.objects.filter(status='new').count(),
        'confirmed_count': Order.objects.filter(status='confirmed').count(),
        'packed_count': Order.objects.filter(status='packed').count(),
        'delivered_count': Order.objects.filter(status='delivered').count(),
    }
    template = (
        'marketplace/_staff_order_list.html'
        if request.headers.get('HX-Request') == 'true'
        else 'marketplace/staff_orders.html'
    )
    response = render(request, template, context)
    if request.headers.get('HX-Request') == 'true':
        response['HX-Trigger-After-Swap'] = json.dumps({
            'staffOrdersUpdated': {'newCount': context['new_count']},
        })
    return response


@login_required
def staff_order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    return render(request, 'marketplace/staff_order_detail.html', {'order': order})


@login_required
@require_POST
def staff_order_action(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    action_statuses = {
        'confirm': 'confirmed',
        'packed': 'packed',
        'delivered': 'delivered',
        'cancel': 'cancelled',
    }
    action = request.POST.get('action')
    if action not in action_statuses:
        messages.error(request, 'Please select a valid order action.')
        return redirect('staff_order_detail', order_id=order.id)

    update_fields = ['status', 'updated_at']
    order.status = action_statuses[action]
    if action == 'confirm':
        payment_method = request.POST.get('payment_method')
        if payment_method:
            if payment_method not in {'cash', 'momo'}:
                messages.error(request, 'Please select a valid payment method.')
                return redirect('staff_order_detail', order_id=order.id)
            order.payment_method = payment_method
            update_fields.append('payment_method')
    order.save(update_fields=update_fields)
    return redirect('staff_order_detail', order_id=order.id)


@login_required
def staff_stock(request):
    q = request.GET.get('q', '').strip()
    products = []
    if q:
        products = Product.objects.filter(
            Q(name__icontains=q) | Q(code__icontains=q)
        ).order_by('name')[:50]
    return render(request, 'marketplace/staff_stock.html', {
        'products': products,
        'q': q,
    })


@login_required
@require_POST
def staff_toggle_stock(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if product.manually_disabled:
        product.manually_disabled = False
        product.is_active = product.stock_quantity > 0
    else:
        product.manually_disabled = True
        product.is_active = False
    product.save(update_fields=['manually_disabled', 'is_active'])
    return render(request, 'marketplace/_staff_product_row.html', {'product': product})


@login_required
def staff_order_slip(request, order_id):
    order = get_object_or_404(
        Order.objects.select_related(
            'customer', 'customer__apartment'
        ).prefetch_related('items__product'),
        id=order_id,
    )
    return render(request, 'marketplace/staff_order_slip.html', {'order': order})