"""Staff screen: merge product categories (move all products of some categories into one)."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .category_merge import MergeError, categories_overview, make_plan, merge, undo_merge
from .models import CategoryMerge

RECENT_MERGES = 5


def _form_context(request, **extra):
    context = {
        'categories': categories_overview(),
        'recent_merges': CategoryMerge.objects.all()[:RECENT_MERGES],
        'ticked': {int(i) for i in request.POST.getlist('source') if i.isdigit()},
        'target_id': request.POST.get('target', ''),
        'new_name': request.POST.get('new_name', ''),
        'target_mode': request.POST.get('target_mode', 'existing'),
    }
    context.update(extra)
    return context


def _request_args(request):
    """The merge request as typed: which categories, and the target (new name wins when that option is chosen)."""
    sources = request.POST.getlist('source')
    if request.POST.get('target_mode') == 'new':
        return sources, None, request.POST.get('new_name', '')
    return sources, request.POST.get('target'), ''


@login_required
def staff_category_merge(request):
    """GET: the form. POST: check the request and show a preview (nothing changes yet)."""
    if request.method != 'POST':
        return render(request, 'marketplace/staff_category_merge.html', _form_context(request))
    try:
        plan = make_plan(*_request_args(request))
    except MergeError as error:
        return render(request, 'marketplace/staff_category_merge.html', _form_context(request, error=str(error)))
    return render(request, 'marketplace/staff_category_merge_preview.html', {
        'plan': plan,
        'source_ids': [row['group'].pk for row in plan['sources']],
        'target_id': plan['target'].pk if plan['target'] else '',
        'new_name': plan['new_name'],
        'target_mode': request.POST.get('target_mode', 'existing'),
    })


@login_required
@require_POST
def staff_category_merge_apply(request):
    try:
        record = merge(*_request_args(request))
    except MergeError as error:
        return render(request, 'marketplace/staff_category_merge.html', _form_context(request, error=str(error)))
    return render(request, 'marketplace/staff_category_merge_done.html', {'record': record})


@login_required
@require_POST
def staff_category_merge_undo(request, merge_id):
    record = get_object_or_404(CategoryMerge, pk=merge_id)
    try:
        restored = undo_merge(record)
    except MergeError as error:
        return render(request, 'marketplace/staff_category_merge.html', _form_context(request, error=str(error)))
    return render(request, 'marketplace/staff_category_merge.html', _form_context(
        request, notice=f'Undone: {restored} product{"s" if restored != 1 else ""} put back in their old categories.',
    ))