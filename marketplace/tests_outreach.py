"""Tests for order timestamps, QR attribution numbers and the owner dashboard section.
Run with:  python manage.py test marketplace.tests_outreach"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .dashboard_stats import clean_range, delivery_time_stats, outreach_stats, window
from .models import Apartment, Customer, Order, QRScan


def make_order(customer, status='new', total='10000', created=None, **extra):
    order = Order.objects.create(customer=customer, status=status, total_amount=Decimal(total), **extra)
    if created is not None:
        Order.objects.filter(pk=order.pk).update(created_at=created)   # auto_now_add cannot be set directly
    return Order.objects.get(pk=order.pk)


class OrderStageTimestampTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(phone_number='0700000001')

    def test_stage_times_are_recorded_once_each(self):
        order = make_order(self.customer)
        self.assertIsNone(order.confirmed_at)
        order.status = 'confirmed'
        order.save(update_fields=['status', 'updated_at'])          # the way staff_order_action saves
        order.refresh_from_db()
        first_confirmed = order.confirmed_at
        self.assertIsNotNone(first_confirmed)
        order.status = 'packed'
        order.save()
        order.status = 'delivered'
        order.save()
        order.refresh_from_db()
        self.assertEqual(order.confirmed_at, first_confirmed)       # not overwritten
        self.assertIsNotNone(order.packed_at)
        self.assertIsNotNone(order.delivered_at)

    def test_cancelled_orders_get_no_stage_time(self):
        order = make_order(self.customer)
        order.status = 'cancelled'
        order.save()
        order.refresh_from_db()
        self.assertEqual((order.confirmed_at, order.packed_at, order.delivered_at), (None, None, None))


class RangeTests(TestCase):
    def test_clean_range(self):
        self.assertEqual(clean_range('7'), 7)
        self.assertEqual(clean_range('90'), 90)
        for bad in (None, '', 'abc', '5', '1000'):
            self.assertEqual(clean_range(bad), 30)

    def test_window_covers_n_days_ending_on_the_end_date(self):
        end = timezone.localdate()
        start, last = window(end, 7)
        self.assertEqual((last - start).days, 6)


class DeliveryTimeTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(phone_number='0700000002')
        self.today = timezone.localdate()

    def delivered(self, total_minutes, confirm=3, packing=5):
        created = timezone.now() - timedelta(hours=1)
        order = make_order(self.customer, status='delivered', created=created)
        confirmed = created + timedelta(minutes=confirm)
        packed = confirmed + timedelta(minutes=packing)
        Order.objects.filter(pk=order.pk).update(
            confirmed_at=confirmed, packed_at=packed, delivered_at=created + timedelta(minutes=total_minutes),
        )

    def test_not_enough_data(self):
        for minutes in (12, 14, 16):
            self.delivered(minutes)
        stats = delivery_time_stats(self.today, self.today)
        self.assertEqual(stats['count'], 3)
        self.assertFalse(stats['enough'])

    def test_median_p80_and_breakdown(self):
        for minutes in (10, 12, 14, 16, 30):
            self.delivered(minutes)
        stats = delivery_time_stats(self.today, self.today)
        self.assertTrue(stats['enough'])
        self.assertEqual(stats['count'], 5)
        self.assertEqual(stats['median'], 14)
        self.assertEqual(stats['p80'], 19)           # 80th percentile of 10,12,14,16,30: 16 + 0.2 * (30 - 16) = 18.8
        self.assertEqual(stats['confirm'], 3)
        self.assertEqual(stats['packing'], 5)
        self.assertEqual(stats['ride'], 6)           # median of (total - 8 min) = 14 - 8

    def test_undelivered_and_old_orders_are_ignored(self):
        make_order(self.customer, status='packed')
        old = timezone.now() - timedelta(days=60)
        order = make_order(self.customer, status='delivered', created=old)
        Order.objects.filter(pk=order.pk).update(delivered_at=old + timedelta(minutes=20))
        stats = delivery_time_stats(self.today - timedelta(days=6), self.today)
        self.assertEqual(stats['count'], 0)
        self.assertIsNone(stats['median'])


class OutreachStatsTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.sunrise = Apartment.objects.create(name='Sunrise')
        self.palm = Apartment.objects.create(name='Palm Court')
        self.ann = Customer.objects.create(phone_number='0700000010', apartment=self.sunrise)
        self.ben = Customer.objects.create(phone_number='0700000011', apartment=self.sunrise)

    def scan(self, apartment, visitor, source=''):
        QRScan.objects.create(apartment=apartment, visitor=visitor, source=source)

    def test_scans_orders_first_and_repeat_and_placements(self):
        self.scan(self.sunrise, 'v1', 'gate')
        self.scan(self.sunrise, 'v2', 'gate')
        self.scan(self.sunrise, 'v1', 'corridor')
        self.scan(self.palm, 'v3', '')
        # Ann: first order from a gate scan, then a repeat one. Ben: one first order. Plus a cancelled order.
        make_order(self.ann, total='20000', qr_apartment=self.sunrise, qr_source='gate')
        make_order(self.ann, total='15000', qr_apartment=self.sunrise, qr_source='gate')
        make_order(self.ben, total='5000', qr_apartment=self.sunrise, qr_source='corridor')
        make_order(self.ben, status='cancelled', total='99999', qr_apartment=self.sunrise, qr_source='gate')
        make_order(self.ben, total='7000')   # not from a QR code: must not be counted

        stats = outreach_stats(self.today, self.today)
        self.assertTrue(stats['has_data'])
        rows = {r['name']: r for r in stats['apartments']}
        sunrise = rows['Sunrise']
        self.assertEqual((sunrise['scans'], sunrise['phones']), (3, 2))
        self.assertEqual((sunrise['orders'], sunrise['first_orders'], sunrise['repeat_orders']), (3, 2, 1))
        self.assertEqual(sunrise['ordering_customers'], 2)
        self.assertEqual(sunrise['revenue'], Decimal('40000'))
        palm = rows['Palm Court']
        self.assertEqual((palm['scans'], palm['orders']), (1, 0))
        self.assertEqual(stats['apartments'][0]['name'], 'Sunrise')     # most orders first

        placements = {r['label']: r for r in stats['placements']}
        self.assertEqual((placements['gate']['scans'], placements['gate']['orders']), (2, 2))
        self.assertEqual((placements['corridor']['scans'], placements['corridor']['orders']), (1, 1))
        self.assertEqual(placements['No placement tag']['scans'], 1)

        totals = stats['totals']
        self.assertEqual((totals['scans'], totals['phones'], totals['orders']), (4, 3, 3))
        self.assertEqual((totals['first_orders'], totals['repeat_orders']), (2, 1))

    def test_a_customer_who_ordered_before_the_scan_is_a_repeat_order(self):
        make_order(self.ann, total='1000', created=timezone.now() - timedelta(days=40))   # earlier, no QR
        make_order(self.ann, total='2000', qr_apartment=self.sunrise, qr_source='gate')
        stats = outreach_stats(self.today - timedelta(days=6), self.today)
        row = stats['apartments'][0]
        self.assertEqual((row['orders'], row['first_orders'], row['repeat_orders']), (1, 0, 1))

    def test_empty_period(self):
        self.assertFalse(outreach_stats(self.today, self.today)['has_data'])


class DashboardPageTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user('boss', password='pw', is_staff=True)
        self.client.force_login(self.staff)
        self.today = timezone.localdate()
        self.apartment = Apartment.objects.create(name='Sunrise')
        self.customer = Customer.objects.create(phone_number='0700000020', apartment=self.apartment)

    def test_empty_dashboard_renders(self):
        response = self.client.get('/owner/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No QR code scans in this period yet.')
        self.assertContains(response, 'Not enough deliveries recorded yet')

    def test_dashboard_with_data_shows_numbers_and_respects_range(self):
        QRScan.objects.create(apartment=self.apartment, visitor='v1', source='gate')
        make_order(self.customer, total='25000', qr_apartment=self.apartment, qr_source='gate')
        for minutes in (10, 12, 14, 16, 30):
            created = timezone.now() - timedelta(hours=2)
            order = make_order(self.customer, status='delivered', created=created)
            Order.objects.filter(pk=order.pk).update(delivered_at=created + timedelta(minutes=minutes))
        response = self.client.get('/owner/?qr_days=7')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['outreach_days'], 7)
        self.assertContains(response, 'By apartment')
        self.assertContains(response, 'Sunrise')
        self.assertContains(response, 'gate')
        self.assertContains(response, '14 min')
        self.assertContains(response, '25,000')
        self.assertNotContains(response, 'Not enough deliveries recorded yet')
        # unknown range values fall back to the default
        self.assertEqual(self.client.get('/owner/?qr_days=3').context['outreach_days'], 30)