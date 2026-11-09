"""Merge product categories (product groups): move every product of the chosen categories into one target.

The merge is recorded in CategoryMerge, so it can be undone. The emptied categories are not deleted: they simply
disappear from the shop (a category with no products is never listed) and you can delete them in the admin later.
"""
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from .models import CategoryMerge, FamilyDismissal, Product, ProductGroup, Shelf

MAX_NAME = 255


class MergeError(Exception):
    """A problem the staff member can fix; the message is shown to them."""


def categories_overview():
    return list(ProductGroup.objects.annotate(n=Count('product')).order_by('name'))


def _clean_ids(raw_ids):
    seen = []
    for raw in raw_ids:
        if str(raw).isdigit() and int(raw) not in seen:
            seen.append(int(raw))
    return seen


def make_plan(source_ids, target_id=None, new_name=''):
    """Check the request and describe what a merge would do. Changes nothing."""
    ids = _clean_ids(source_ids)
    if not ids:
        raise MergeError('Tick at least one category to merge.')
    sources = list(ProductGroup.objects.filter(pk__in=ids).annotate(n=Count('product')).order_by('name'))
    if len(sources) != len(ids):
        raise MergeError('One of the categories no longer exists. Reload the page and try again.')

    new_name = ' '.join((new_name or '').split())
    target = None
    if new_name:
        if len(new_name) > MAX_NAME:
            raise MergeError('That category name is too long.')
        target = ProductGroup.objects.filter(name__iexact=new_name).first()       # the same name means the same category
    elif target_id and str(target_id).isdigit():
        target = ProductGroup.objects.filter(pk=int(target_id)).first()
        if target is None:
            raise MergeError('The category you chose no longer exists. Reload the page and try again.')
    else:
        raise MergeError('Choose which category the products should move into, or type a name for a new one.')

    if target is not None and target.pk in {s.pk for s in sources}:
        raise MergeError(f'"{target.name}" is both a category to merge and the place the products go. Untick it, or choose a different target.')

    rows = [{
        'group': s, 'count': s.n,
        'shelves': Shelf.objects.filter(group=s).count(),
        'pinned': s.home_order is not None,
    } for s in sources]
    return {
        'sources': rows,
        'target': target,
        'new_name': '' if target is not None else new_name,
        'total': sum(r['count'] for r in rows),
        'shelves': sum(r['shelves'] for r in rows),
        'pinned': sum(1 for r in rows if r['pinned']),
        'target_count': Product.objects.filter(group=target).count() if target is not None else 0,
    }


def _move_dismissals(source_id, target_id):
    """Family suggestions you dismissed in a category stay dismissed after its products move."""
    prefix = f'{source_id}:'
    for dismissal in FamilyDismissal.objects.filter(key__startswith=prefix):
        new_key = f'{target_id}:{dismissal.key[len(prefix):]}'
        if FamilyDismissal.objects.filter(key=new_key).exists():
            dismissal.delete()
        else:
            dismissal.key = new_key
            dismissal.save(update_fields=['key'])


@transaction.atomic
def merge(source_ids, target_id=None, new_name=''):
    plan = make_plan(source_ids, target_id, new_name)
    sources = [row['group'] for row in plan['sources']]
    target, created = plan['target'], False
    pinned_orders = [s.home_order for s in sources if s.home_order is not None]

    if target is None:
        target = ProductGroup(name=plan['new_name'])
        picture = next((s.image.name for s in sources if getattr(s, 'image', None)), '')
        if picture:
            target.image = picture              # the new category keeps the first picture it finds
        target.save()
        created = True

    target_order_before = target.home_order
    if target.home_order is None and pinned_orders:
        target.home_order = min(pinned_orders)  # if a pinned category moves in, the target takes its place in the row
        target.save(update_fields=['home_order'])

    moves, moved = [], 0
    for source in sources:
        product_ids = list(Product.objects.filter(group=source).values_list('pk', flat=True))
        shelf_ids = list(Shelf.objects.filter(group=source).values_list('pk', flat=True))
        Product.objects.filter(pk__in=product_ids).update(group=target)
        Shelf.objects.filter(pk__in=shelf_ids).update(group=target)
        ProductGroup.objects.filter(pk=source.pk).update(home_order=None)
        _move_dismissals(source.pk, target.pk)
        moves.append({
            'source_id': source.pk, 'source_name': source.name, 'home_order': source.home_order,
            'product_ids': product_ids, 'shelf_ids': shelf_ids,
        })
        moved += len(product_ids)

    return CategoryMerge.objects.create(
        target=target, target_name=target.name, target_was_created=created,
        target_home_order_before=target_order_before, moves=moves, products_moved=moved,
    )


@transaction.atomic
def undo_merge(record):
    """Put products, shelves and pinned positions back, as far as they are still where the merge left them."""
    if record.undone_at:
        raise MergeError('That merge was already undone.')
    target = record.target
    restored = 0
    if target is not None:
        for move in record.moves:
            source = ProductGroup.objects.filter(pk=move['source_id']).first()
            if source is None:
                continue                                    # the category was deleted since: nowhere to put them back
            restored += Product.objects.filter(pk__in=move['product_ids'], group=target).update(group=source)
            Shelf.objects.filter(pk__in=move['shelf_ids'], group=target).update(group=source)
            if move['home_order'] is not None:
                ProductGroup.objects.filter(pk=source.pk, home_order__isnull=True).update(home_order=move['home_order'])
        target.refresh_from_db()
        if target.home_order != record.target_home_order_before and record.target_home_order_before is None:
            ProductGroup.objects.filter(pk=target.pk).update(home_order=None)
        if record.target_was_created and not Product.objects.filter(group=target).exists() \
                and not Shelf.objects.filter(group=target).exists():
            target.delete()                                 # a category this merge created, and nothing is in it now
    now = timezone.now()
    CategoryMerge.objects.filter(pk=record.pk).update(undone_at=now)      # update(), because the target may just have been deleted
    record.undone_at = now
    return restored