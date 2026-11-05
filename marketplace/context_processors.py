"""
Context processors for the marketplace app.
"""

from django.conf import settings
from django.utils.functional import SimpleLazyObject

from .models import Apartment, Customer, StoreConfig


def vapid_public_key(request):
    return {'VAPID_PUBLIC_KEY': getattr(settings, 'VAPID_PUBLIC_KEY', '')}


def _load_config():
    config, _ = StoreConfig.objects.get_or_create(pk=1)
    return config


def _load_customer(request):
    session = getattr(request, 'session', None)
    customer_id = session.get('customer_id') if session is not None else None
    if not customer_id:
        return None
    try:
        return Customer.objects.select_related('apartment').get(pk=customer_id)
    except (Customer.DoesNotExist, ValueError, TypeError):
        return None


def _load_current_apartment(request):
    """The apartment to show in the header: a scanned QR code wins, then the saved customer's."""
    session = getattr(request, 'session', None)
    scanned_id = session.get('qr_apartment_id') if session is not None else None
    if scanned_id:
        apartment = Apartment.objects.filter(pk=scanned_id, is_served=True).first()
        if apartment is not None:
            return apartment
    customer = _load_customer(request)
    return customer.apartment if customer else None


def _cart_quantities(request):
    """{ 'product id': quantity } for the cart in the session, so cards can show a stepper."""
    session = getattr(request, 'session', None)
    cart = session.get('cart', {}) if session is not None else {}
    quantities = {}
    for key, quantity in cart.items():
        try:
            quantities[str(key)] = int(quantity)
        except (TypeError, ValueError):
            continue
    return quantities


def store_context(request):
    return {
        'config': SimpleLazyObject(_load_config),
        'current_customer': SimpleLazyObject(lambda: _load_customer(request)),
        'current_apartment': SimpleLazyObject(lambda: _load_current_apartment(request)),
        # Staff and owner pages should not show the customer header or the floating cart bar.
        'in_staff_area': request.path.startswith(('/staff', '/owner')),
        'cart_quantities': SimpleLazyObject(lambda: _cart_quantities(request)),

    }
