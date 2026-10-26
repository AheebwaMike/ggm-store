from django.conf import settings


def vapid_public_key(request):
    return {'VAPID_PUBLIC_KEY': settings.VAPID_PUBLIC_KEY}

from django.utils.functional import SimpleLazyObject

from .models import Customer, StoreConfig


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


def store_context(request):
    return {
        'config': SimpleLazyObject(_load_config),
        'current_customer': SimpleLazyObject(lambda: _load_customer(request)),
    }
