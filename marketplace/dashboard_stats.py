"""Numbers for the owner dashboard: how the QR outreach is doing, and how long deliveries really take."""
import math
from datetime import timedelta

from django.db.models import Count, Min

from .models import Apartment, Order, QRScan

RANGE_CHOICES = (7, 30, 90)
DEFAULT_RANGE = 30
MIN_DELIVERIES_FOR_TIMES = 5


def clean_range(raw):
    """Number of days from the query string, limited to the choices offered."""
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_RANGE
    return days if days in RANGE_CHOICES else DEFAULT_RANGE


def window(end_date, days):
    """(first day, last day) covering `days` days that end on end_date."""
    return end_date - timedelta(days=days - 1), end_date


def _percentile(sorted_values, fraction):
    """Linear-interpolated percentile of an already sorted list (None for an empty list)."""
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return sorted_values[int(position)]
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (position - lower)


def _minutes(delta):
    return delta.total_seconds() / 60


# ------------------------------------------------------------------ outreach

def outreach_stats(start, end):
    """Scans and the orders that came from them, per apartment and per placement."""
    scans = QRScan.objects.filter(scanned_at__date__gte=start, scanned_at__date__lte=end)
    orders = list(
        Order.objects.filter(
            created_at__date__gte=start, created_at__date__lte=end, qr_apartment__isnull=False,
        ).exclude(status='cancelled').values('id', 'customer_id', 'qr_apartment_id', 'qr_source', 'total_amount')
    )

    # An order is a customer's "first" if it is the earliest non-cancelled order they have ever placed.
    customer_ids = {order['customer_id'] for order in orders}
    first_order_ids = set(
        Order.objects.exclude(status='cancelled')
        .filter(customer_id__in=customer_ids)
        .values('customer_id')
        .annotate(first=Min('id'))
        .values_list('first', flat=True)
    )

    def empty_row():
        return {'scans': 0, 'phones': 0, 'orders': 0, 'first_orders': 0, 'revenue': 0, 'customers': set()}

    def add_orders(rows, key_name):
        for order in orders:
            row = rows.setdefault(order[key_name], empty_row())
            row['orders'] += 1
            row['revenue'] += order['total_amount']
            row['customers'].add(order['customer_id'])
            if order['id'] in first_order_ids:
                row['first_orders'] += 1

    by_apartment = {}
    for row in scans.values('apartment_id').annotate(total=Count('id'), phones=Count('visitor', distinct=True)):
        entry = by_apartment.setdefault(row['apartment_id'], empty_row())
        entry['scans'], entry['phones'] = row['total'], row['phones']
    add_orders(by_apartment, 'qr_apartment_id')

    by_source = {}
    for row in scans.values('source').annotate(total=Count('id'), phones=Count('visitor', distinct=True)):
        entry = by_source.setdefault(row['source'], empty_row())
        entry['scans'], entry['phones'] = row['total'], row['phones']
    add_orders(by_source, 'qr_source')

    names = dict(Apartment.objects.filter(pk__in=by_apartment.keys()).values_list('pk', 'name'))

    def finish(row):
        row['ordering_customers'] = len(row.pop('customers'))
        row['repeat_orders'] = row['orders'] - row['first_orders']
        return row

    apartment_rows = []
    for apartment_id, row in by_apartment.items():
        row = finish(row)
        row['name'] = names.get(apartment_id, 'Removed apartment')
        apartment_rows.append(row)
    apartment_rows.sort(key=lambda r: (-r['orders'], -r['scans'], r['name']))

    placement_rows = []
    for source, row in by_source.items():
        row = finish(row)
        row['label'] = source or 'No placement tag'
        placement_rows.append(row)
    placement_rows.sort(key=lambda r: (-r['orders'], -r['scans'], r['label']))

    totals = {
        'scans': sum(r['scans'] for r in apartment_rows),
        'phones': scans.values('visitor').distinct().count(),
        'orders': sum(r['orders'] for r in apartment_rows),
        'first_orders': sum(r['first_orders'] for r in apartment_rows),
        'revenue': sum(r['revenue'] for r in apartment_rows),
    }
    totals['repeat_orders'] = totals['orders'] - totals['first_orders']

    return {
        'apartments': apartment_rows,
        'placements': placement_rows,
        'totals': totals,
        'has_data': bool(apartment_rows),
    }


# ------------------------------------------------------------------ delivery times

def delivery_time_stats(start, end):
    """How long delivered orders really took, in whole minutes (None where there is no data)."""
    orders = Order.objects.filter(
        status='delivered', delivered_at__isnull=False,
        created_at__date__gte=start, created_at__date__lte=end,
    ).values('created_at', 'confirmed_at', 'packed_at', 'delivered_at')

    totals, confirm, packing, ride = [], [], [], []
    for order in orders:
        total = _minutes(order['delivered_at'] - order['created_at'])
        if total >= 0:
            totals.append(total)
        if order['confirmed_at']:
            value = _minutes(order['confirmed_at'] - order['created_at'])
            if value >= 0:
                confirm.append(value)
        if order['confirmed_at'] and order['packed_at']:
            value = _minutes(order['packed_at'] - order['confirmed_at'])
            if value >= 0:
                packing.append(value)
        if order['packed_at']:
            value = _minutes(order['delivered_at'] - order['packed_at'])
            if value >= 0:
                ride.append(value)

    def median(values):
        result = _percentile(sorted(values), 0.5)
        return None if result is None else round(result)

    totals.sort()
    p80 = _percentile(totals, 0.8)
    return {
        'count': len(totals),
        'enough': len(totals) >= MIN_DELIVERIES_FOR_TIMES,
        'minimum_needed': MIN_DELIVERIES_FOR_TIMES,
        'median': median(totals),
        'p80': None if p80 is None else round(p80),
        'confirm': median(confirm),
        'packing': median(packing),
        'ride': median(ride),
    }