"""Tests for the apartment QR feature. Run with:  python manage.py test marketplace.tests_qr"""
import tempfile
import unittest

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import Client, TestCase, override_settings

from .models import Apartment, QRScan

try:
    import cv2
    import numpy as np
except ImportError:
    _CV2_AVAILABLE = False
else:
    _CV2_AVAILABLE = True

PHONE_UA = 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36'

# Pages that extend base.html use {% static %}. Under production-style settings (manifest static storage)
# that fails in tests because collectstatic has not run, so the page tests use plain static storage.
PLAIN_STATIC = override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})


class ApartmentSlugTests(TestCase):
    def test_slug_is_created_from_name_and_is_unique(self):
        first = Apartment.objects.create(name='Sunrise Apartments')
        second = Apartment.objects.create(name='Sunrise  Apartments!')
        self.assertEqual(first.slug, 'sunrise-apartments')
        self.assertEqual(second.slug, 'sunrise-apartments-2')

    def test_existing_slug_is_kept_when_name_changes(self):
        apartment = Apartment.objects.create(name='Block B')
        apartment.name = 'Block B Renamed'
        apartment.save()
        self.assertEqual(Apartment.objects.get(pk=apartment.pk).slug, 'block-b')


@PLAIN_STATIC
class LandingTests(TestCase):
    def setUp(self):
        self.apartment = Apartment.objects.create(name='Sunrise Apartments', welcome_message='')
        self.client = Client(HTTP_USER_AGENT=PHONE_UA)
        self.url = f'/a/{self.apartment.slug}/'

    def test_scan_remembers_apartment_logs_and_redirects_home(self):
        response = self.client.get(self.url + '?s=Gate')
        self.assertRedirects(response, '/', fetch_redirect_response=False)
        self.assertEqual(self.client.session['qr_apartment_id'], self.apartment.pk)
        self.assertEqual(self.client.session['qr_source'], 'gate')
        scan = QRScan.objects.get()
        self.assertEqual((scan.apartment, scan.source), (self.apartment, 'gate'))
        self.assertIn('ggm_vid', response.cookies)
        texts = [m.message for m in get_messages(response.wsgi_request)]
        self.assertEqual(texts, ['Welcome! We deliver to Sunrise Apartments.'])

    def test_custom_welcome_message_is_used(self):
        self.apartment.welcome_message = 'Karibu Sunrise!'
        self.apartment.save()
        response = self.client.get(self.url)
        self.assertEqual([m.message for m in get_messages(response.wsgi_request)], ['Karibu Sunrise!'])

    def test_same_phone_same_code_counts_once_but_new_placement_counts(self):
        self.client.get(self.url + '?s=gate')
        self.client.get(self.url + '?s=gate')
        self.assertEqual(QRScan.objects.count(), 1)
        self.client.get(self.url + '?s=corridor')
        self.assertEqual(QRScan.objects.count(), 2)

    def test_different_phones_count_separately(self):
        self.client.get(self.url)
        Client(HTTP_USER_AGENT=PHONE_UA).get(self.url)
        self.assertEqual(QRScan.objects.count(), 2)

    def test_bots_and_link_previews_are_not_counted(self):
        for agent in ('WhatsApp/2.23.20.0 A', 'facebookexternalhit/1.1', 'Googlebot/2.1', ''):
            bot = Client(HTTP_USER_AGENT=agent)
            response = bot.get(self.url)
            self.assertEqual(response.status_code, 302)
            self.assertNotIn('qr_apartment_id', bot.session)
        self.assertEqual(QRScan.objects.count(), 0)

    def test_unknown_slug_is_404(self):
        self.assertEqual(self.client.get('/a/does-not-exist/').status_code, 404)

    def test_unserved_apartment_shows_honest_page_logs_but_does_not_set_apartment(self):
        far = Apartment.objects.create(name='Far Away Court', is_served=False)
        response = self.client.get(f'/a/{far.slug}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'We do not deliver to Far Away Court yet')
        self.assertNotIn('qr_apartment_id', self.client.session)
        self.assertEqual(QRScan.objects.filter(apartment=far).count(), 1)

    def test_scan_sets_header_apartment_via_context_processor(self):
        self.client.get(self.url)
        # any page that uses base.html shows the scanned apartment
        staff = get_user_model().objects.create_user('s', password='p')
        self.client.force_login(staff)
        response = self.client.get('/staff/qr/')
        self.assertEqual(response.context['current_apartment'].pk, self.apartment.pk)
        self.assertTrue(response.context['in_staff_area'])
        self.assertNotContains(response, 'Deliver to')   # the customer header is hidden in the staff area


@PLAIN_STATIC
class StaffToolTests(TestCase):
    def setUp(self):
        self.apartment = Apartment.objects.create(name='Sunrise Apartments')
        self.staff = get_user_model().objects.create_user('staff', password='pw')

    def test_login_required(self):
        for path in ('/staff/qr/', f'/staff/qr/{self.apartment.pk}/poster/', f'/staff/qr/{self.apartment.pk}/download/png/'):
            self.assertEqual(self.client.get(path).status_code, 302)

    @override_settings(SITE_BASE_URL='')   # the warning only shows while the address is not configured
    def test_list_page_renders_and_assigns_missing_slugs(self):
        Apartment.objects.filter(pk=self.apartment.pk).update(slug=None)
        self.client.force_login(self.staff)
        response = self.client.get('/staff/qr/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '/a/sunrise-apartments/')
        self.assertContains(response, 'SITE_BASE_URL')   # warning while it is not configured

    @override_settings(SITE_BASE_URL='https://ggm-test.onrender.com/')
    @unittest.skipUnless(_CV2_AVAILABLE, 'cv2 or numpy not installed')
    def test_png_contains_the_exact_link_and_is_scannable(self):
        self.client.force_login(self.staff)
        response = self.client.get(f'/staff/qr/{self.apartment.pk}/download/png/?tag=Gate')
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertIn('ggm-qr-sunrise-apartments-gate.png', response['Content-Disposition'])
        image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_GRAYSCALE)
        self.assertGreaterEqual(image.shape[0], 1500)          # print quality
        # Phone cameras downscale what they see; OpenCV's basic detector is happiest around 800px.
        image = cv2.resize(image, (800, 800), interpolation=cv2.INTER_AREA)
        decoded, _points, _ = cv2.QRCodeDetector().detectAndDecode(image)
        self.assertEqual(decoded, 'https://ggm-test.onrender.com/a/sunrise-apartments/?s=gate')

    @override_settings(SITE_BASE_URL='https://ggm-test.onrender.com')
    def test_svg_download_and_poster(self):
        self.client.force_login(self.staff)
        svg = self.client.get(f'/staff/qr/{self.apartment.pk}/download/svg/')
        self.assertEqual(svg['Content-Type'], 'image/svg+xml')
        self.assertIn(b'<svg', svg.content)
        poster = self.client.get(f'/staff/qr/{self.apartment.pk}/poster/?tag=gate')
        self.assertEqual(poster.status_code, 200)
        self.assertContains(poster, 'ggm-test.onrender.com/a/sunrise-apartments')
        self.assertContains(poster, '<svg')
        self.assertContains(poster, 'Sunrise Apartments')

    def test_unknown_format_is_404(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(f'/staff/qr/{self.apartment.pk}/download/pdf/').status_code, 404)