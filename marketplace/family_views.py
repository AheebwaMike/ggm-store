"""Staff screen: group products into families (sizes, flavours, packs) from suggestions, one tap at a time."""
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .family_suggestions import suggest_families
from .models import Family, FamilyDismissal, Product

MAX_SHOWN = 20
KIND_CHOICES = [('', 'Guess from the labels'), ('size', 'Sizes'), ('flavour', 'Flavours'), ('pack', 'Packs'), ('type', 'Types')]
VALID_KINDS = {value for value, _label in KIND_CHOICES}
MAX_LABEL = 50
MAX_NAME = 255          # family name (Product.parent_group)
MAX_PRODUCT_NAME = 255  # Product.name


def _ungrouped(queryset):
    return queryset.filter(Q(parent_group__isnull=True) | Q(parent_group=''))


@login_required
def staff_families(request):
    suggestions = suggest_families()
    return render(request, 'marketplace/staff_families.html', {
        'suggestions': suggestions[:MAX_SHOWN],
        'total': len(suggestions),
        'shown': min(len(suggestions), MAX_SHOWN),
        'kind_choices': KIND_CHOICES,
    })


def _card_from_post(request, error):
    member_ids = [int(i) for i in request.POST.getlist('member') if i.isdigit()]
    checked = {int(i) for i in request.POST.getlist('use') if i.isdigit()}
    products = {p.pk: p for p in Product.objects.filter(pk__in=member_ids)}
    members = [
        {
            'product': products[pk],
            'name': request.POST.get(f'name_{pk}', products[pk].name),
            'label': request.POST.get(f'label_{pk}', ''),
            'checked': pk in checked,
        }
        for pk in member_ids if pk in products
    ]
    return {
        'key': request.POST.get('key', ''),
        'name': request.POST.get('family_name', ''),
        'existing': request.POST.get('existing') == '1',
        'existing_count': 0,
        'kind_guess': request.POST.get('kind', ''),
        'members': members,
        'error': error,
    }


@login_required
@require_POST
def staff_family_accept(request):
    name = ' '.join(request.POST.get('family_name', '').split())
    kind = request.POST.get('kind', '')
    selected = list(dict.fromkeys(int(i) for i in request.POST.getlist('use') if i.isdigit()))
    labels = {pk: ' '.join(request.POST.get(f'label_{pk}', '').split()) for pk in selected}

    def fail(message):
        return render(request, 'marketplace/_family_card.html', {
            's': _card_from_post(request, message), 'kind_choices': KIND_CHOICES,
        })

    if not name:
        return fail('Give the family a name.')
    if len(name) > MAX_NAME:
        return fail('That family name is too long.')
    if kind not in VALID_KINDS:
        return fail('Choose one of the kinds in the list.')

    existing_name = (
        Product.objects.exclude(parent_group__isnull=True).exclude(parent_group='')
        .filter(parent_group__iexact=name).values_list('parent_group', flat=True).first()
    )
    family_name = existing_name or name
    existing_labels = set()
    if existing_name:
        existing_labels = {
            label.lower() for label in Product.objects.filter(parent_group__iexact=existing_name)
            .values_list('variant_label', flat=True) if label
        }

    products = list(_ungrouped(Product.objects.filter(pk__in=selected)))
    skipped = len(selected) - len(products)
    if len(products) < (1 if existing_name else 2):
        return fail('Tick at least two products to make a family.' if not existing_name
                    else 'Tick at least one product to add.')

    chosen = []
    new_names = {}
    for product in products:
        posted_name = request.POST.get(f'name_{product.pk}')
        new_name = product.name if posted_name is None else ' '.join(posted_name.split())
        if not new_name:
            return fail(f'The name of "{product.name}" cannot be empty.')
        if len(new_name) > MAX_PRODUCT_NAME:
            return fail(f'The name "{new_name[:40]}..." is too long (255 characters at most).')
        new_names[product.pk] = new_name
        label = labels[product.pk]
        if not label:
            return fail(f'"{product.name}" needs a label, for example 1KG or Chocolate.')
        if len(label) > MAX_LABEL:
            return fail(f'The label for "{product.name}" is too long (50 characters at most).')
        chosen.append(label.lower())
    if len(set(chosen)) != len(chosen):
        return fail('Two products have the same label. Each option needs its own label.')
    clash = existing_labels.intersection(chosen)
    if clash:
        return fail(f'The family already has an option called "{sorted(clash)[0]}".')

    previous = []
    renamed = 0
    with transaction.atomic():
        Family.objects.get_or_create(name=family_name)
        for product in products:
            previous.append({
                'id': product.pk,
                'name': product.name,
                'new_name': new_names[product.pk],
                'parent_group': product.parent_group or '',
                'parent_group_is_null': product.parent_group is None,
                'label': product.variant_label or '',
                'label_is_null': product.variant_label is None,
                'kind': product.variant_kind,
            })
            if new_names[product.pk] != product.name:
                renamed += 1
            product.name = new_names[product.pk]
            product.parent_group = family_name
            product.variant_label = labels[product.pk]
            if kind:
                product.variant_kind = kind
            product.save(update_fields=['name', 'parent_group', 'variant_label', 'variant_kind'])

    return render(request, 'marketplace/_family_done.html', {
        'family_name': family_name, 'count': len(products), 'skipped': skipped, 'previous': previous, 'renamed': renamed,
        'added_to_existing': bool(existing_name),
    })


@login_required
@require_POST
def staff_family_dismiss(request):
    key = request.POST.get('key', '').strip()
    if key and len(key) <= 300 and ':' in key:
        FamilyDismissal.objects.get_or_create(key=key)
    return HttpResponse('')


@login_required
@require_POST
def staff_family_undo(request):
    name = request.POST.get('family_name', '')
    restored = 0
    with transaction.atomic():
        for raw_id in request.POST.getlist('id'):
            if not raw_id.isdigit():
                continue
            pk = int(raw_id)
            parent_group = request.POST.get(f'prev_parent_{pk}', '')
            if request.POST.get(f'prev_parent_null_{pk}', '1') == '1':
                parent_group = None
            variant_label = request.POST.get(f'prev_label_{pk}', '')
            if request.POST.get(f'prev_label_null_{pk}', '1') == '1':
                variant_label = None
            updated = Product.objects.filter(pk=pk, parent_group=name).update(
                parent_group=parent_group,
                variant_label=variant_label,
                variant_kind=request.POST.get(f'prev_kind_{pk}', ''),
            )
            restored += updated
            old_name = ' '.join(request.POST.get(f'prev_name_{pk}', '').split())
            new_name = request.POST.get(f'new_name_{pk}', '')
            if updated and old_name and new_name and old_name != new_name:
                # only if the name is still the one we set; a later edit by someone else is left alone
                Product.objects.filter(pk=pk, name=new_name).update(name=old_name)
    return render(request, 'marketplace/_family_undone.html', {'restored': restored, 'family_name': name})