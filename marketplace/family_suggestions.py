"""Suggest product families (sizes, flavours, packs) from the names of ungrouped products.

Nothing is changed here: this only reads products and proposes. Staff review every suggestion
on /staff/families/ and press "Group" (or "Not a family") themselves.

Examples:
    KAKIRA SUGAR 1KG, KAKIRA SUGAR 2KG, KAKIRA SUGAR 5KG  ->  family "Kakira Sugar", labels 1KG, 2KG, 5KG
    BIC PEN BLUE, BIC PEN BLACK                            ->  family "Bic Pen", labels Blue, Black (to check)
"""
import re
import string
from collections import defaultdict

from django.db.models import Count

from .models import FamilyDismissal, Product
from .shelves import _looks_like_a_size

MAX_FLAVOUR_FAMILY = 12

_UNITS = (
    r'kgs?|kilos?|gms?|g|mg|ltrs?|litres?|liters?|l|ml|cl|oz|lbs?|pcs?|pk|pkts?|packs?|packets?|dozen|doz|'
    r'sachets?|tins?|bottles?|cartons?|bags?|boxes|box|rolls?|sheets?|pages?|pgs?|leaves'
)
_MEASURE = re.compile(rf'(?<![A-Za-z0-9.,])(\d+(?:[.,]\d+)?|\d+/\d+)\s*({_UNITS})(?![A-Za-z])', re.IGNORECASE)
_MULTIPACK = re.compile(r'(?<![A-Za-z0-9])[xX]\s?(\d+)(?![A-Za-z0-9])')
_EDGE_PUNCTUATION = re.compile(r'^[\s\-\u2013_/,.:*()\[\]]+|[\s\-\u2013_/,.:*()\[\]]+$')


def normalise(text):
    """Lowercase words only, so 'Kakira  Sugar!' and 'KAKIRA SUGAR' compare equal."""
    return ' '.join(re.findall(r'[a-z0-9]+', (text or '').lower()))


def pretty(text):
    """'KAKIRA SUGAR' -> 'Kakira Sugar' (keeps apostrophes sensible)."""
    return string.capwords(' '.join((text or '').split()).lower())


def split_name(name):
    """Split a product name into (base, label), or (name, '') when it has no size or pack in it."""
    spans = [(m.start(), m.end(), re.sub(r'\s+', '', m.group(0)).upper().replace(',', '.')) for m in _MEASURE.finditer(name)]
    spans += [(m.start(), m.end(), 'X' + m.group(1)) for m in _MULTIPACK.finditer(name)]
    if not spans:
        return name.strip(), ''
    spans.sort()
    base, last = [], 0
    for start, end, _label in spans:
        base.append(name[last:start])
        last = end
    base.append(name[last:])
    base_text = _EDGE_PUNCTUATION.sub('', ' '.join(''.join(base).split()))
    return base_text, ' '.join(label for _s, _e, label in spans)


def _existing_family_names():
    names = (
        Product.objects.exclude(parent_group__isnull=True).exclude(parent_group='')
        .values_list('parent_group', flat=True).distinct()
    )
    return {normalise(name): name for name in names}


def _existing_family_sizes():
    """{family name: how many products it already has}."""
    rows = (
        Product.objects.exclude(parent_group__isnull=True).exclude(parent_group='')
        .values('parent_group').annotate(n=Count('id'))
    )
    return {row['parent_group']: row['n'] for row in rows}


def _kind_guess(labels):
    return 'size' if labels and all(_looks_like_a_size(label) for label in labels) else ''


def suggest_families():
    """All suggestions, best first: sizes (confident) before flavours (worth a check)."""
    ungrouped = list(
        Product.objects.filter(is_active=True, selling_price__gt=0)
        .filter(parent_group__isnull=True) | Product.objects.filter(is_active=True, selling_price__gt=0, parent_group='')
    )
    existing = _existing_family_names()
    existing_sizes = _existing_family_sizes()
    dismissed = set(FamilyDismissal.objects.values_list('key', flat=True))

    clusters = defaultdict(list)
    leftovers = []
    for product in ungrouped:
        base, label = split_name(product.name)
        if label and normalise(base):
            clusters[(product.group_id or 0, normalise(base))].append((product, base, label))
        else:
            leftovers.append(product)

    suggestions, used = [], set()

    def add(group_id, norm_key, members, display_name, confidence):
        key = f'{group_id}:{norm_key}'
        if key in dismissed:
            return
        labels = [label for _product, label in members]
        if len({label.lower() for label in labels}) != len(labels) or any(not label for label in labels):
            return
        family_exists = norm_key in existing
        if not family_exists and len(members) < 2:
            return
        members = sorted(members, key=lambda pair: (pair[0].selling_price, pair[0].name))
        family_name = existing.get(norm_key) or display_name
        suggestions.append({
            'key': key,
            'name': family_name,
            'existing': family_exists,
            'existing_count': existing_sizes.get(family_name, 0),
            'kind_guess': _kind_guess([label for _p, label in members]),
            'confidence': confidence,
            'members': [{'product': product, 'label': label, 'checked': True} for product, label in members],
        })
        used.update(product.pk for product, _label in members)

    for (group_id, norm_key), rows in clusters.items():
        add(group_id, norm_key, [(p, label) for p, _b, label in rows], pretty(rows[0][1]), 'sizes')

    prefixes = defaultdict(list)
    for product in leftovers:
        if product.pk in used:
            continue
        words = re.findall(r'[A-Za-z0-9]+', product.name)
        if len(words) >= 3 and words[-1].isalpha() and len(words[-1]) >= 2:
            prefixes[(product.group_id or 0, normalise(' '.join(words[:-1])))].append((product, words))
    for (group_id, norm_key), rows in prefixes.items():
        if not 2 <= len(rows) <= MAX_FLAVOUR_FAMILY:
            continue
        members = [(product, words[-1].title()) for product, words in rows]
        add(group_id, norm_key, members, pretty(' '.join(rows[0][1][:-1])), 'check')

    flavours_of_a_size = defaultdict(list)
    for (group_id, _norm), rows in clusters.items():
        for product, base, label in rows:
            if product.pk in used:
                continue
            words = re.findall(r'[A-Za-z0-9]+', base)
            if len(words) >= 3 and words[-1].isalpha() and len(words[-1]) >= 2:
                flavours_of_a_size[(group_id, normalise(' '.join(words[:-1])), label.lower())].append((product, words, label))
    for (group_id, norm_key, _label), rows in flavours_of_a_size.items():
        if not 2 <= len(rows) <= MAX_FLAVOUR_FAMILY:
            continue
        size_label = rows[0][2]
        family_key = f'{norm_key} {size_label.lower()}'
        members = [(product, words[-1].title()) for product, words, _l in rows]
        add(group_id, normalise(family_key), members, f"{pretty(' '.join(rows[0][1][:-1]))} {size_label}", 'check')

    suggestions.sort(key=lambda s: (s['confidence'] != 'sizes', -len(s['members']), s['name'].lower()))
    return suggestions
