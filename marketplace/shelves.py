"""What the home page shows: shelves of products, the category row and the "discover" grid.

Everything here is data-driven and honest: a shelf only appears when it has enough real products,
"popular" means really sold recently, and "new" means really added recently.
"""
import re
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import Product, ProductGroup, Shelf, StoreConfig

MIN_SHELF_ITEMS = 4          # a shelf with fewer products is hidden, never shown half empty
OVERFETCH = 4                # fetch extra rows so collapsing size families still leaves enough cards
POPULAR_DAYS = 14
NEW_DAYS = 14
DISCOVER_PAGE_SIZE = 12
DISCOVER_MAX_ITEMS = 120
HOME_CATEGORY_LIMIT = 12


def get_config():
    config, _created = StoreConfig.objects.get_or_create(pk=1)
    return config


# ------------------------------------------------------------------ which products can be shown

def sellable_products():
    """Products a customer can actually buy right now."""
    return Product.objects.filter(
        is_active=True, manually_disabled=False, selling_price__gt=0, stock_quantity__gt=0,
    ).select_related('unit')


def loose_products():
    """Products that can be found by search: active and priced (out-of-stock ones show as such)."""
    return Product.objects.filter(is_active=True, selling_price__gt=0).select_related('unit')


def with_photo(queryset):
    return queryset.exclude(image='').exclude(image__isnull=True)


def _units_sold(extra=None):
    """Units sold (cancelled orders ignored), optionally narrowed, as an annotation expression."""
    condition = ~Q(orderitem__order__status='cancelled')
    if extra is not None:
        condition &= extra
    return Coalesce(Sum('orderitem__quantity', filter=condition), Value(Decimal('0')), output_field=DecimalField())


# ------------------------------------------------------------------ what kind of choice a family offers

_MEASURE = re.compile(
    r'^\s*(\d+([.,]\d+)?|\d+/\d+|half|quarter)?\s*'
    r'(kgs?|kilos?|g|gm|gms|mg|l|ltrs?|litres?|liters?|ml|cl|oz|lbs?|pcs?|pieces?|packs?|pkts?|packets?|dozen|'
    r'tins?|sachets?|bottles?|cartons?|bags?|boxes|box|rolls?|sheets?)\b',
    re.IGNORECASE,
)
_SIZE_WORDS = {'small', 'medium', 'large', 'xl', 'xxl', 'mini', 'jumbo', 'family', 'regular', 's', 'm', 'l'}
_KIND_PLURALS = {'size': 'sizes', 'flavour': 'flavours', 'pack': 'packs', 'type': 'types', 'option': 'options'}
_KIND_SINGULARS = {'size': 'size', 'flavour': 'flavour', 'pack': 'pack', 'type': 'type', 'option': 'option'}


def _looks_like_a_size(label):
    label = (label or '').strip()
    return bool(label) and (bool(_MEASURE.match(label)) or label.lower() in _SIZE_WORDS)


def family_kind(variants):
    """'size', 'flavour', 'pack', 'type' (set in the admin) or a guess: all-measure labels mean sizes, else 'option'."""
    explicit = next((v.variant_kind for v in variants if getattr(v, 'variant_kind', '')), '')
    if explicit:
        return explicit
    labels = [v.variant_label for v in variants]
    if labels and all(_looks_like_a_size(label) for label in labels):
        return 'size'
    return 'option'


def kind_label(kind, count):
    """'3 sizes', '5 flavours', '4 options'."""
    return f'{count} {_KIND_PLURALS.get(kind, "options")}'


def kind_word(kind):
    """'size', 'flavour' ... for sentences such as 'Choose a size'."""
    return _KIND_SINGULARS.get(kind, 'option')


# ------------------------------------------------------------------ turning products into cards

def simple_item(product):
    return {
        'product': product, 'image_product': product, 'is_group': False,
        'min_price': product.selling_price, 'max_price': product.selling_price, 'variant_count': 0,
    }


def family_item(variants, parent_name):
    """One card for a family of sizes or flavours: shows 'From UGX ...'."""
    from .models import Family

    variants = sorted(variants, key=lambda v: (v.selling_price, v.name))
    representative = variants[0]
    kind = family_kind(variants)
    family = Family.objects.filter(name=parent_name).only('cover_image').first()
    if family and family.cover_image:
        image_product = representative
        cover_override = family
    else:
        cover_override = None
        image_product = next((v for v in variants if v.image), representative)
    return {
        'product': representative,
        'image_product': image_product,
        'cover_override': cover_override,
        'is_group': True,
        'min_price': variants[0].selling_price,
        'max_price': variants[-1].selling_price,
        'variant_count': len(variants),
        'kind': kind,
        'kind_label': kind_label(kind, len(variants)),
        'parent_name': parent_name,
    }


def build_items(rows, sibling_queryset, limit):
    """Cards in the order of `rows`; a family of variants becomes one card where its first member appears."""
    parents = {product.parent_group for product in rows if product.parent_group}
    families = {}
    if parents:
        for variant in sibling_queryset.filter(parent_group__in=parents):
            families.setdefault(variant.parent_group, []).append(variant)

    items, seen_families = [], set()
    for product in rows:
        if product.parent_group:
            if product.parent_group in seen_families:
                continue
            seen_families.add(product.parent_group)
            variants = families.get(product.parent_group) or [product]
            items.append(family_item(variants, product.parent_group) if len(variants) > 1 else simple_item(variants[0]))
        else:
            items.append(simple_item(product))
        if len(items) >= limit:
            break
    return items


# ------------------------------------------------------------------ shelves

def shelf_queryset(shelf, config):
    queryset = sellable_products()
    if config.shelves_require_photo:
        queryset = with_photo(queryset)

    if shelf.kind == Shelf.CURATED:
        return queryset.filter(shelfitem__shelf=shelf).order_by('shelfitem__position', 'shelfitem__id')
    if shelf.kind == Shelf.CATEGORY:
        if shelf.group_id is None:
            return queryset.none()
        return queryset.filter(group_id=shelf.group_id).annotate(sold=_units_sold()).order_by('-sold', 'name')
    if shelf.kind == Shelf.NEW:
        since = timezone.now() - timedelta(days=NEW_DAYS)
        return queryset.filter(created_at__gte=since).order_by('-created_at', '-id')
    if shelf.kind == Shelf.UNDER_PRICE:
        if shelf.max_price is None:
            return queryset.none()
        return queryset.filter(selling_price__lte=shelf.max_price).annotate(sold=_units_sold()).order_by('-sold', 'name')
    if shelf.kind == Shelf.POPULAR:
        since = timezone.now() - timedelta(days=POPULAR_DAYS)
        recent = _units_sold(Q(orderitem__order__created_at__gte=since))
        return queryset.annotate(recent=recent).filter(recent__gt=0).order_by('-recent', 'name')
    return queryset.none()


def shelf_items(shelf, config, limit=None):
    limit = limit or shelf.max_items
    rows = list(shelf_queryset(shelf, config)[: limit * OVERFETCH])
    return build_items(rows, sellable_products(), limit)


def home_shelves(config):
    """Shelves that have enough products to be worth showing, in the order set in the admin."""
    blocks = []
    for shelf in Shelf.objects.filter(is_active=True):
        items = shelf_items(shelf, config)
        if len(items) >= MIN_SHELF_ITEMS:
            blocks.append({'shelf': shelf, 'items': items})
    return blocks


def seed_default_shelves(config):
    """Create the starter shelves once. Afterwards they are yours to edit, hide or delete in the admin."""
    if config.shelves_seeded:
        return
    defaults = [
        ('Everyday essentials', Shelf.CURATED, {}, 10),
        ('Popular right now', Shelf.POPULAR, {}, 20),
        ('Under UGX 3,000', Shelf.UNDER_PRICE, {'max_price': Decimal('3000')}, 30),
        ('New arrivals', Shelf.NEW, {}, 40),
    ]
    for title, kind, extra, position in defaults:
        Shelf.objects.get_or_create(title=title, defaults={'kind': kind, 'position': position, **extra})
    config.shelves_seeded = True
    config.save(update_fields=['shelves_seeded'])


# ------------------------------------------------------------------ categories

def _available_count():
    return Count(
        'product',
        filter=Q(product__is_active=True, product__manually_disabled=False,
                 product__selling_price__gt=0, product__stock_quantity__gt=0),
    )


def home_categories(limit=HOME_CATEGORY_LIMIT):
    """The category row: the ones you pinned, or else the categories with the most products to buy."""
    pinned = list(ProductGroup.objects.filter(home_order__isnull=False).order_by('home_order', 'name')[:limit])
    if pinned:
        return pinned
    return list(
        ProductGroup.objects.annotate(available=_available_count()).filter(available__gt=0)
        .order_by('-available', 'name')[:10]
    )


def categories_with_counts():
    return list(
        ProductGroup.objects.annotate(available=_available_count()).filter(available__gt=0).order_by('name')
    )


# ------------------------------------------------------------------ discover grid

def interleave_by_group(rows):
    """Reorder so neighbours come from different categories (not twelve milks in a row)."""
    buckets, order = {}, []
    for product in rows:
        if product.group_id not in buckets:
            buckets[product.group_id] = []
            order.append(product.group_id)
        buckets[product.group_id].append(product)

    result = []
    for round_number in range(max((len(b) for b in buckets.values()), default=0)):
        for key in order:
            if round_number < len(buckets[key]):
                result.append(buckets[key][round_number])
    return result


def discover_page(config, page):
    """One page of the endless 'Discover more' grid and whether another page follows."""
    queryset = sellable_products()
    if config.shelves_require_photo:
        queryset = with_photo(queryset)
    queryset = queryset.annotate(sold=_units_sold()).order_by('-sold', '-id')
    rows = interleave_by_group(list(queryset[: DISCOVER_MAX_ITEMS * 3]))
    items = build_items(rows, sellable_products(), DISCOVER_MAX_ITEMS)
    start = (page - 1) * DISCOVER_PAGE_SIZE
    end = start + DISCOVER_PAGE_SIZE
    return items[start:end], end < len(items)