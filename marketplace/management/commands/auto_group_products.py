import re

from django.core.management.base import BaseCommand
from django.db import transaction

from marketplace.models import Product


VARIANT_PATTERNS = (
    re.compile(r'\b\d+(?:\.\d+)?\s*(?:KGS|KG|LTR|ML|GM|G|L)\b', re.IGNORECASE),
    re.compile(r'\b\d+(?:\.\d+)?\s*(?:PCS|PIECES)\b', re.IGNORECASE),
    re.compile(r'\b(?:SMALL|MEDIUM|LARGE|BIG|XL|XXL)\b', re.IGNORECASE),
)
FLAVOUR_KEYWORDS = (
    'CHILLI',
    'TOMATO',
    'BBQ',
    'SALT',
    'VINEGAR',
    'CHICKEN',
    'BEEF',
    'STRAWBERRY',
    'VANILLA',
    'CHOCOLATE',
    'MANGO',
    'APPLE',
)


def find_product_variant(name):
    name_upper = name.upper()
    for pattern in VARIANT_PATTERNS:
        match = pattern.search(name_upper)
        if match:
            base_name = pattern.sub('', name_upper).strip(' -_,')
            return base_name.title(), match.group(0).strip().upper()

    for flavour in FLAVOUR_KEYWORDS:
        pattern = re.compile(rf'\b{re.escape(flavour)}\b', re.IGNORECASE)
        match = pattern.search(name_upper)
        if match:
            base_name = pattern.sub('', name_upper, count=1).strip(' -_,')
            return base_name.title(), match.group(0).title()

    return None


class Command(BaseCommand):
    help = 'Auto-groups products based on name patterns'

    def handle(self, *args, **kwargs):
        self.stdout.write('Starting auto-grouping...')
        products_to_update = []

        for product in Product.objects.all().iterator():
            if product.parent_group:
                continue
            grouping = find_product_variant(product.name)
            if grouping is None:
                continue

            parent_group, variant_label = grouping
            if not parent_group:
                continue

            product.parent_group = parent_group
            product.variant_label = variant_label
            products_to_update.append(product)

        with transaction.atomic():
            if products_to_update:
                Product.objects.bulk_update(
                    products_to_update,
                    ['parent_group', 'variant_label'],
                    batch_size=500,
                )

        self.stdout.write(self.style.SUCCESS(
            f'Successfully auto-grouped {len(products_to_update)} products.'
        ))
        self.stdout.write(
            'Review the results in the Django Admin. You can manually adjust any grouping errors there.'
        )
