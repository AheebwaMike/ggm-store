"""QR codes for apartments.

- apartment_landing: what a scan opens (/a/<slug>/). Remembers the apartment, logs the scan, goes home.
- staff_qr_list / staff_qr_poster / staff_qr_download: staff tools to print or export the codes.

The QR code contains only the apartment's permanent link. Everything else (welcome text,
offers, where the link leads) can change on the server without reprinting anything.
"""
import io
import math
import uuid
from datetime import timedelta

import segno
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from .models import Apartment, QRScan, StoreConfig

VISITOR_COOKIE = 'ggm_vid'
VISITOR_COOKIE_MAX_AGE = 60 * 60 * 24 * 365
DEDUPE_WINDOW = timedelta(minutes=30)

# Link-preview fetchers and crawlers must not count as scans or set up a visit.
BOT_MARKERS = (
    'bot', 'crawler', 'spider', 'preview', 'facebookexternalhit',
    'whatsapp/', 'slack', 'curl/', 'python-requests', 'headless',
)

PLACEMENT_TAGS = ['gate', 'corridor', 'lift', 'reception', 'notice-board', 'flyer', 'whatsapp']


# ---------------------------------------------------------------- helpers

def _is_bot(request):
    agent = request.META.get('HTTP_USER_AGENT', '').lower()
    return not agent or any(marker in agent for marker in BOT_MARKERS)


def _clean_tag(raw):
    """Placement tag from the query string: lowercase letters, digits and dashes only."""
    return slugify(raw or '')[:40]


def _base_url(request):
    """Address that goes into the QR code.

    Set SITE_BASE_URL (for example https://your-app.onrender.com) so every code carries the
    same, explicit address no matter which device or host the staff used to open this page.
    """
    configured = getattr(settings, 'SITE_BASE_URL', '')
    if configured:
        return configured.rstrip('/')
    return request.build_absolute_uri('/').rstrip('/')


def _landing_path(apartment):
    return reverse('apartment_landing', args=[apartment.slug])


def _scan_url(request, apartment, tag=''):
    url = f'{_base_url(request)}{_landing_path(apartment)}'
    return f'{url}?s={tag}' if tag else url


def _qr(url):
    # High error correction: a scratched or weathered poster still scans.
    return segno.make_qr(url, error='h')


def _svg_bytes(url):
    buffer = io.BytesIO()
    _qr(url).save(buffer, kind='svg', scale=10, border=4, dark='#000000', light='#ffffff')
    return buffer.getvalue()


def _svg_inline(url):
    """SVG markup that scales with CSS, for the printable poster page."""
    buffer = io.BytesIO()
    _qr(url).save(
        buffer, kind='svg', border=4, dark='#000000', light='#ffffff',
        xmldecl=False, omitsize=True, nl=False,
    )
    return buffer.getvalue().decode('utf-8')


def _png_bytes(url, target_pixels=2000):
    qr = _qr(url)
    width, _height = qr.symbol_size(scale=1, border=4)
    scale = max(10, math.ceil(target_pixels / width))
    buffer = io.BytesIO()
    qr.save(buffer, kind='png', scale=scale, border=4, dark='#000000', light='#ffffff')
    return buffer.getvalue()


def _log_scan(apartment, tag, visitor_id):
    """Record a scan, counting the same phone at the same code only once per half hour."""
    since = timezone.now() - DEDUPE_WINDOW
    already = QRScan.objects.filter(
        apartment=apartment, source=tag, visitor=visitor_id, scanned_at__gte=since,
    ).exists()
    if not already:
        QRScan.objects.create(apartment=apartment, source=tag, visitor=visitor_id)


# ---------------------------------------------------------------- what a scan opens

def apartment_landing(request, slug):
    apartment = Apartment.objects.filter(slug=slug).first()
    if apartment is None:
        raise Http404('Unknown apartment link')

    is_bot = _is_bot(request)
    tag = _clean_tag(request.GET.get('s', ''))
    visitor_id = request.COOKIES.get(VISITOR_COOKIE) or uuid.uuid4().hex

    if not is_bot:
        _log_scan(apartment, tag, visitor_id)   # logged even if we do not deliver there yet: that is demand

    if not apartment.is_served:
        config, _created = StoreConfig.objects.get_or_create(pk=1)
        response = render(request, 'marketplace/apartment_not_served.html', {
            'apartment': apartment,
            'config': config,
            'whatsapp_message': f'Hello! Please consider delivering to {apartment.name}.',
        })
    else:
        if not is_bot:
            request.session['qr_apartment_id'] = apartment.pk
            request.session['qr_source'] = tag
            messages.info(
                request,
                apartment.welcome_message or f'Welcome! We deliver to {apartment.name}.',
                extra_tags='welcome',
            )
        response = redirect('home')

    if not is_bot:
        response.set_cookie(
            VISITOR_COOKIE, visitor_id,
            max_age=VISITOR_COOKIE_MAX_AGE, httponly=True, samesite='Lax',
            secure=request.is_secure(),
        )
    return response


# ---------------------------------------------------------------- staff tools

@login_required
def staff_qr_list(request):
    # Apartments created before QR codes existed get their link here, once.
    for apartment in Apartment.objects.filter(slug__isnull=True):
        apartment.save()

    apartments = list(
        Apartment.objects.annotate(
            scan_count=Count('scans'),
            visitor_count=Count('scans__visitor', distinct=True),
            last_scan=Max('scans__scanned_at'),
        ).order_by('name')
    )
    for apartment in apartments:
        apartment.scan_url = _scan_url(request, apartment)

    return render(request, 'marketplace/staff_qr_list.html', {
        'apartments': apartments,
        'placement_tags': PLACEMENT_TAGS,
        'base_url': _base_url(request),
        'base_url_is_configured': bool(getattr(settings, 'SITE_BASE_URL', '')),
    })


@login_required
def staff_qr_poster(request, apartment_id):
    apartment = get_object_or_404(Apartment, pk=apartment_id)
    if not apartment.slug:
        apartment.save()
    tag = _clean_tag(request.GET.get('tag', ''))
    url = _scan_url(request, apartment, tag)
    config, _created = StoreConfig.objects.get_or_create(pk=1)

    readable = f'{_base_url(request)}{_landing_path(apartment)}'.split('://', 1)[-1]
    return render(request, 'marketplace/staff_qr_poster.html', {
        'apartment': apartment,
        'config': config,
        'qr_svg': _svg_inline(url),
        'readable_url': readable,
        'tag': tag,
    })


@login_required
def staff_qr_download(request, apartment_id, fmt):
    if fmt not in ('svg', 'png'):
        raise Http404('Unknown format')
    apartment = get_object_or_404(Apartment, pk=apartment_id)
    if not apartment.slug:
        apartment.save()
    tag = _clean_tag(request.GET.get('tag', ''))
    url = _scan_url(request, apartment, tag)

    if fmt == 'svg':
        body, content_type = _svg_bytes(url), 'image/svg+xml'
    else:
        body, content_type = _png_bytes(url), 'image/png'

    filename = f'ggm-qr-{apartment.slug}{"-" + tag if tag else ""}.{fmt}'
    response = HttpResponse(body, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
