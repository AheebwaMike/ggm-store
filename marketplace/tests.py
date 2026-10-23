from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import Apartment, Customer, Order, OrderItem, Product, StoreConfig


class OwnerDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_superuser(
            username='owner',
            email='owner@example.com',
            password='test-password',
        )
        cls.staff = User.objects.create_user(
            username='staff',
            password='test-password',
            is_staff=True,
        )
        cls.customer = Customer.objects.create(phone_number='1234567890')
        cls.product_a = Product.objects.create(
            code='A001',
            name='Product A',
            selling_price=Decimal('500.00'),
        )
        cls.product_b = Product.objects.create(
            code='B001',
            name='Product B',
            selling_price=Decimal('250.00'),
        )

    def create_order(self, *, status='new', payment_method='cash', total_amount):
        return Order.objects.create(
            customer=self.customer,
            status=status,
            payment_method=payment_method,
            total_amount=total_amount,
        )

    def test_dashboard_shows_today_stats_and_product_quantities(self):
        cash_order = self.create_order(total_amount=Decimal('1000.00'))
        momo_order = self.create_order(
            payment_method='momo',
            total_amount=Decimal('500.00'),
        )
        cancelled_order = self.create_order(
            status='cancelled',
            total_amount=Decimal('900.00'),
        )
        old_order = self.create_order(total_amount=Decimal('2000.00'))
        Order.objects.filter(pk=old_order.pk).update(
            created_at=timezone.now() - timedelta(days=1),
        )

        OrderItem.objects.create(
            order=cash_order,
            product=self.product_a,
            quantity=Decimal('2.00'),
            price_at_time_of_order=Decimal('500.00'),
        )
        OrderItem.objects.create(
            order=momo_order,
            product=self.product_a,
            quantity=Decimal('1.00'),
            price_at_time_of_order=Decimal('500.00'),
        )
        OrderItem.objects.create(
            order=momo_order,
            product=self.product_b,
            quantity=Decimal('3.00'),
            price_at_time_of_order=Decimal('250.00'),
        )
        OrderItem.objects.create(
            order=cancelled_order,
            product=self.product_b,
            quantity=Decimal('10.00'),
            price_at_time_of_order=Decimal('250.00'),
        )

        self.client.force_login(self.owner)
        response = self.client.get('/owner/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_orders'], 2)
        self.assertEqual(response.context['total_revenue'], Decimal('1500.00'))
        self.assertEqual(response.context['avg_order_value'], Decimal('750.00'))
        self.assertEqual(response.context['cash_orders'], 1)
        self.assertEqual(response.context['momo_orders'], 1)
        self.assertEqual(
            list(response.context['top_products']),
            [
                {'product__name': 'Product A', 'total_qty': Decimal('3')},
                {'product__name': 'Product B', 'total_qty': Decimal('3')},
            ],
        )
        self.assertEqual(response.context['selected_date'], timezone.localdate())
        self.assertEqual(len(response.context['seven_day_trend']), 7)
        self.assertEqual(response.context['seven_day_trend'][-1]['date'], timezone.localdate())

    def test_dashboard_filters_historical_date_and_builds_seven_day_trend(self):
        selected_date = timezone.localdate() - timedelta(days=1)
        historical_order = self.create_order(total_amount=Decimal('1200.00'))
        Order.objects.filter(pk=historical_order.pk).update(
            created_at=timezone.now() - timedelta(days=1),
        )
        cancelled_order = self.create_order(
            status='cancelled',
            total_amount=Decimal('500.00'),
        )
        Order.objects.filter(pk=cancelled_order.pk).update(
            created_at=timezone.now() - timedelta(days=1),
        )

        self.client.force_login(self.owner)
        response = self.client.get('/owner/', {'date': selected_date.isoformat()})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_date'], selected_date)
        self.assertFalse(response.context['is_today'])
        self.assertEqual(response.context['total_orders'], 1)
        self.assertEqual(response.context['total_revenue'], Decimal('1200.00'))
        self.assertEqual(response.context['recent_orders'].count(), 1)
        self.assertEqual(len(response.context['seven_day_trend']), 7)
        self.assertEqual(response.context['seven_day_trend'][-1]['date'], selected_date)
        self.assertEqual(response.context['seven_day_trend'][-1]['revenue'], Decimal('1200.00'))
        self.assertContains(response, 'Showing data for')

    def test_invalid_dashboard_date_defaults_to_today(self):
        self.client.force_login(self.owner)

        response = self.client.get('/owner/?date=not-a-date')

        self.assertEqual(response.context['selected_date'], timezone.localdate())
        self.assertTrue(response.context['is_today'])

    def test_dashboard_requires_staff_access(self):
        self.client.force_login(get_user_model().objects.create_user(
            username='customer-user',
            password='test-password',
        ))

        response = self.client.get('/owner/')

        self.assertRedirects(response, '/admin/login/?next=%2Fowner%2F')

    def test_staff_orders_shows_owner_dashboard_link_only_to_superusers(self):
        self.client.force_login(self.staff)
        staff_response = self.client.get('/staff/')
        self.assertNotContains(staff_response, 'href="/owner/"')

        self.client.force_login(self.owner)
        owner_response = self.client.get('/staff/')
        self.assertContains(owner_response, 'href="/owner/"')


class StaffManifestTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username='manifest-staff',
            password='test-password',
            is_staff=True,
        )

    def create_order(
        self,
        *,
        phone,
        apartment=None,
        status='confirmed',
        payment_method='cash',
        total_amount,
        name='',
        note='',
    ):
        customer = Customer.objects.create(
            phone_number=phone,
            name=name,
            apartment=apartment,
        )
        return Order.objects.create(
            customer=customer,
            status=status,
            payment_method=payment_method,
            total_amount=total_amount,
            note=note,
        )

    def test_manifest_shows_today_active_orders_grouped_and_summed(self):
        apartment_a = Apartment.objects.create(name='Apartment A')
        apartment_b = Apartment.objects.create(name='Apartment B')
        order_b = self.create_order(
            phone='0700000001',
            apartment=apartment_b,
            total_amount=Decimal('10000.00'),
        )
        order_a = self.create_order(
            phone='0700000002',
            apartment=apartment_a,
            payment_method='momo',
            status='packed',
            total_amount=Decimal('2500.00'),
            note='Call when you reach the gate',
        )
        self.create_order(
            phone='0700000003',
            total_amount=Decimal('500.00'),
            status='new',
        )
        old_order = self.create_order(
            phone='0700000004',
            total_amount=Decimal('900.00'),
            status='packed',
        )
        Order.objects.filter(pk=old_order.pk).update(
            created_at=timezone.now() - timedelta(days=1),
        )

        self.client.force_login(self.staff)
        response = self.client.get('/staff/manifest/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_orders'], 2)
        self.assertEqual(response.context['cash_to_collect'], Decimal('10000.00'))
        self.assertEqual(response.context['momo_to_collect'], Decimal('2500.00'))
        content = response.content.decode()
        self.assertLess(content.index('Apartment A'), content.index('Apartment B'))
        self.assertIn(f'#{order_a.pk}', content)
        self.assertIn(f'#{order_b.pk}', content)
        self.assertNotIn(f'#{old_order.pk}', content)
        self.assertIn('MOMO TO COLLECT', content)
        self.assertIn('aria-label="Delivery completion checkbox"', content)
        self.assertIn('Note: Call when you reach the gate', content)

        self.client.force_login(self.staff)
        detail_response = self.client.get(f'/staff/order/{order_a.pk}/')
        self.assertContains(detail_response, 'Delivery Instructions')
        self.assertContains(detail_response, 'Call when you reach the gate')

    def test_manifest_requires_login_and_staff_header_links_to_it(self):
        response = self.client.get('/staff/manifest/')
        self.assertRedirects(response, '/login/?next=/staff/manifest/')

        self.client.force_login(self.staff)
        staff_response = self.client.get('/staff/')
        self.assertContains(staff_response, 'href="/staff/manifest/"')
        self.assertContains(staff_response, 'target="_blank"')


class DeliveryPricingTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            code='PRICE001',
            name='Test Product',
            selling_price=Decimal('15000.00'),
        )
        self.apartment = Apartment.objects.create(name='Test Apartment')
        self.config = StoreConfig.objects.create()
        session = self.client.session
        session['cart'] = {str(self.product.pk): 1}
        session.save()

    def test_defaults_and_cart_free_delivery_progress(self):
        self.assertEqual(self.config.delivery_fee, Decimal('2000.00'))
        self.assertEqual(self.config.free_delivery_threshold, Decimal('35000.00'))
        self.assertEqual(self.config.minimum_order_value, Decimal('0.00'))

        self.config.free_delivery_threshold = Decimal('20000.00')
        self.config.save()
        response = self.client.get('/cart/')

        self.assertContains(response, 'Spend <strong>UGX 5000</strong> more')
        self.assertContains(response, 'UGX 17000')

    def test_apartment_override_and_free_delivery_threshold(self):
        self.apartment.delivery_fee_override = Decimal('0.00')
        self.apartment.save()
        response = self.client.get(
            f'/checkout/summary/?apartment={self.apartment.pk}',
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'FREE')
        self.assertContains(response, 'UGX 15000')

        self.config.free_delivery_threshold = Decimal('15000.00')
        self.config.save()
        response = self.client.get(
            f'/checkout/summary/?apartment={self.apartment.pk}',
        )
        self.assertContains(response, 'FREE')

    def test_checkout_persists_delivery_fee_and_grand_total(self):
        response = self.client.post('/checkout/', {
            'phone': '0701234567',
            'name': 'Test Buyer',
            'apartment': str(self.apartment.pk),
            'unit_number': '4A',
            'payment_method': 'cash',
            'note': 'Call when you reach the gate',
        })

        order = Order.objects.get()
        self.assertRedirects(response, f'/order/success/{order.pk}/')
        self.assertEqual(order.delivery_fee, Decimal('2000.00'))
        self.assertEqual(order.total_amount, Decimal('17000.00'))
        self.assertEqual(order.note, 'Call when you reach the gate')
        success_response = self.client.get(f'/order/success/{order.pk}/')
        self.assertContains(success_response, 'UGX 2000')
        self.assertContains(success_response, 'UGX 17000')

    def test_checkout_preserves_note_when_validation_fails(self):
        response = self.client.post('/checkout/', {
            'phone': '',
            'name': '',
            'apartment': str(self.apartment.pk),
            'unit_number': '',
            'payment_method': 'cash',
            'note': 'Call when you reach the gate',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Call when you reach the gate')

    def test_minimum_order_value_prevents_checkout(self):
        self.config.minimum_order_value = Decimal('20000.00')
        self.config.save()

        response = self.client.get('/checkout/')

        self.assertRedirects(response, '/cart/')
        self.assertEqual(Order.objects.count(), 0)

    def test_staff_settings_persist_valid_values_and_reject_invalid_values(self):
        user = get_user_model().objects.create_user(
            username='settings-staff',
            password='test-password',
        )
        self.client.force_login(user)

        response = self.client.get('/staff/settings/')
        self.assertContains(response, 'value="2000.00"')
        self.assertContains(response, 'value="35000.00"')
        self.assertContains(response, 'value="0.00"')

        response = self.client.post('/staff/settings/', {
            'delivery_fee': '3000',
            'free_delivery_threshold': '20000',
            'minimum_order_value': '1000',
        })
        self.assertRedirects(response, '/staff/settings/')
        self.config.refresh_from_db()
        self.assertEqual(self.config.delivery_fee, Decimal('3000'))
        self.assertEqual(self.config.free_delivery_threshold, Decimal('20000'))
        self.assertEqual(self.config.minimum_order_value, Decimal('1000'))

        response = self.client.post('/staff/settings/', {
            'delivery_fee': '-1',
            'free_delivery_threshold': '20000',
            'minimum_order_value': '1000',
        })
        self.assertEqual(response.status_code, 200)
        self.config.refresh_from_db()
        self.assertEqual(self.config.delivery_fee, Decimal('3000'))


class LowStockAlertTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username='low-stock-staff',
            password='test-password',
            is_staff=True,
        )
        self.owner = get_user_model().objects.create_superuser(
            username='low-stock-owner',
            email='low-stock-owner@example.com',
            password='test-password',
        )
        self.low_stock_product = Product.objects.create(
            code='LOW001',
            name='Low Stock Product',
            stock_quantity=Decimal('2.00'),
            low_stock_threshold=Decimal('5.00'),
            is_active=True,
        )
        self.healthy_product = Product.objects.create(
            code='OK001',
            name='Healthy Product',
            stock_quantity=Decimal('8.00'),
            low_stock_threshold=Decimal('5.00'),
            is_active=True,
        )
        self.disabled_product = Product.objects.create(
            code='OFF001',
            name='Disabled Product',
            stock_quantity=Decimal('1.00'),
            low_stock_threshold=Decimal('5.00'),
            is_active=False,
        )

    def test_owner_dashboard_alerts_on_active_low_stock_only(self):
        self.client.force_login(self.owner)
        response = self.client.get('/owner/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context['low_stock_products']),
            [self.low_stock_product],
        )
        self.assertContains(response, 'Low Stock Alerts')
        self.assertContains(response, 'Low Stock Product')
        self.assertContains(response, 'View all low stock items')

    def test_staff_stock_low_stock_filter_and_warning_badge(self):
        self.client.force_login(self.staff)
        response = self.client.get('/staff/stock/?filter=low_stock')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context['products']),
            [self.low_stock_product],
        )
        self.assertContains(response, '2 left')
        self.assertNotContains(response, 'Healthy Product')
        self.assertNotContains(response, 'Disabled Product')

    def test_staff_stock_search_can_be_combined_with_low_stock_filter(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            '/staff/stock/?filter=low_stock&q=LOW001',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context['products']),
            [self.low_stock_product],
        )
        self.assertEqual(response.context['filter_type'], 'low_stock')
