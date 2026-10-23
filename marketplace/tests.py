import json
from io import BytesIO
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook
from requests import Response
from pywebpush import WebPushException
from django.core.files.uploadedfile import SimpleUploadedFile

from .models import (
    Apartment,
    Customer,
    Order,
    OrderItem,
    Product,
    ProductGroup,
    PushSubscription,
    StoreConfig,
    WhatsAppNotificationLog,
)


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
            'whatsapp_number': ' +256 770-000-000 ',
        })
        self.assertRedirects(response, '/staff/settings/')
        self.config.refresh_from_db()
        self.assertEqual(self.config.delivery_fee, Decimal('3000'))
        self.assertEqual(self.config.free_delivery_threshold, Decimal('20000'))
        self.assertEqual(self.config.minimum_order_value, Decimal('1000'))
        self.assertEqual(self.config.whatsapp_number, '256770000000')

        response = self.client.post('/staff/settings/', {
            'delivery_fee': '-1',
            'free_delivery_threshold': '20000',
            'minimum_order_value': '1000',
        })
        self.assertEqual(response.status_code, 200)
        self.config.refresh_from_db()
        self.assertEqual(self.config.delivery_fee, Decimal('3000'))


class StaffStockUploadTests(TestCase):
    def setUp(self):
        staff = get_user_model().objects.create_user(
            username='stock-upload-staff',
            password='test-password',
            is_staff=True,
        )
        self.client.force_login(staff)
        self.upload_url = reverse('staff_upload_stock')
        self.active_product = Product.objects.create(
            code='STOCK001',
            name='Active Product',
            stock_quantity=Decimal('8.00'),
            is_active=True,
        )
        self.out_of_stock_product = Product.objects.create(
            code='STOCK002',
            name='Out of Stock Product',
            stock_quantity=Decimal('4.00'),
            is_active=True,
        )
        self.disabled_product = Product.objects.create(
            code='STOCK003',
            name='Manually Disabled Product',
            stock_quantity=Decimal('2.00'),
            manually_disabled=True,
            is_active=False,
        )

    def make_workbook_upload(
        self,
        rows,
        *,
        sheet_name='StockSummary',
        filename='stock.xlsx',
    ):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = sheet_name
        for row in rows:
            worksheet.append(row)
        content = BytesIO()
        workbook.save(content)
        workbook.close()
        return SimpleUploadedFile(
            filename,
            content.getvalue(),
            content_type=(
                'application/vnd.openxmlformats-officedocument.'
                'spreadsheetml.sheet'
            ),
        )

    def test_settings_page_displays_stock_upload_form(self):
        response = self.client.get(reverse('staff_settings'))

        self.assertContains(response, 'Update Stock from POS')
        self.assertContains(response, 'StockSummary.xlsx')
        self.assertContains(response, 'action="/staff/settings/upload-stock/"')
        self.assertContains(response, 'name="stock_file"')

    def test_upload_updates_quantities_and_active_flags(self):
        upload = self.make_workbook_upload([
            ('Report generated by POS', None, None, None),
            ('Product Code', 'Product Name', 'Unit', 'Quantity'),
            ('STOCK001', 'Active Product', 'PCS', '12,500'),
            ('STOCK002', 'Out of Stock Product', 'PCS', 0),
            ('STOCK003', 'Manually Disabled Product', 'PCS', 9),
            ('Product Group: Drinks', None, None, None),
            ('Total', None, None, 0),
            ('UNKNOWN', 'Unknown Product', 'PCS', 3),
            ('BADQTY', 'Bad Quantity', 'PCS', 'not a quantity'),
        ])

        response = self.client.post(
            self.upload_url,
            {'stock_file': upload},
            follow=True,
        )

        self.assertContains(
            response,
            'Successfully updated stock for 3 products.',
        )
        self.assertContains(
            response,
            'Skipped 1 stock row(s) with invalid quantities.',
        )
        self.active_product.refresh_from_db()
        self.out_of_stock_product.refresh_from_db()
        self.disabled_product.refresh_from_db()
        self.assertEqual(self.active_product.stock_quantity, Decimal('12500'))
        self.assertTrue(self.active_product.is_active)
        self.assertEqual(self.out_of_stock_product.stock_quantity, Decimal('0'))
        self.assertFalse(self.out_of_stock_product.is_active)
        self.assertEqual(self.disabled_product.stock_quantity, Decimal('9'))
        self.assertFalse(self.disabled_product.is_active)

    def test_upload_does_not_count_unchanged_stock_as_updated(self):
        upload = self.make_workbook_upload([
            ('Product Code', 'Product Name', 'Unit', 'Quantity'),
            ('STOCK001', 'Active Product', 'PCS', '8'),
        ])

        response = self.client.post(
            self.upload_url,
            {'stock_file': upload},
            follow=True,
        )

        self.assertContains(
            response,
            'Successfully updated stock for 0 products.',
        )

    def test_upload_rejects_missing_file_wrong_extension_and_invalid_workbook(self):
        response = self.client.post(self.upload_url, follow=True)
        self.assertContains(response, 'No file uploaded.')

        response = self.client.post(
            self.upload_url,
            {'stock_file': SimpleUploadedFile('stock.csv', b'not xlsx')},
            follow=True,
        )
        self.assertContains(response, 'Please upload an Excel (.xlsx) file.')

        response = self.client.post(
            self.upload_url,
            {'stock_file': SimpleUploadedFile('stock.xlsx', b'not a workbook')},
            follow=True,
        )
        self.assertContains(response, 'Could not read the uploaded Excel file.')

        self.active_product.refresh_from_db()
        self.assertEqual(self.active_product.stock_quantity, Decimal('8.00'))

    def test_upload_rejects_missing_sheet_or_product_code_header(self):
        missing_sheet = self.make_workbook_upload(
            [('Product Code', 'Product Name', 'Unit', 'Quantity')],
            sheet_name='Inventory',
        )
        response = self.client.post(
            self.upload_url,
            {'stock_file': missing_sheet},
            follow=True,
        )
        self.assertContains(
            response,
            "The uploaded file must contain a &#x27;StockSummary&#x27; worksheet.",
        )

        missing_header = self.make_workbook_upload([
            ('Wrong Header', 'Product Name', 'Unit', 'Quantity'),
            ('STOCK001', 'Active Product', 'PCS', 10),
        ])
        response = self.client.post(
            self.upload_url,
            {'stock_file': missing_header},
            follow=True,
        )
        self.assertContains(
            response,
            "Could not find &#x27;Product Code&#x27; header in the uploaded file.",
        )
        self.active_product.refresh_from_db()
        self.assertEqual(self.active_product.stock_quantity, Decimal('8.00'))

    def test_upload_requires_login_and_post(self):
        self.client.logout()
        response = self.client.post(self.upload_url)
        self.assertRedirects(
            response,
            f'/login/?next={self.upload_url}',
        )

        staff = get_user_model().objects.create_user(
            username='second-stock-upload-staff',
            password='test-password',
            is_staff=True,
        )
        self.client.force_login(staff)
        response = self.client.get(self.upload_url)
        self.assertEqual(response.status_code, 405)


class WhatsAppIntegrationTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username='whatsapp-staff',
            password='test-password',
            is_staff=True,
        )
        self.customer = Customer.objects.create(
            phone_number='0701234567',
            name='Test Customer',
        )
        self.order = Order.objects.create(
            customer=self.customer,
            status='new',
            total_amount=Decimal('12500.00'),
        )
        self.config = StoreConfig.objects.create(
            whatsapp_number='256770000000',
        )

    def test_staff_order_detail_builds_notify_link_and_logs_staff_click(self):
        self.client.force_login(self.staff)
        response = self.client.get(f'/staff/order/{self.order.pk}/')

        self.assertContains(response, 'Notify Confirmed on WhatsApp')
        self.assertContains(response, 'https://wa.me/256701234567?text=')
        self.assertContains(response, 'UGX%2012%2C500')

        response = self.client.post(
            f'/staff/order/{self.order.pk}/log-wa/confirmed/',
        )
        self.assertEqual(response.status_code, 204)
        log = WhatsAppNotificationLog.objects.get()
        self.assertEqual(log.order, self.order)
        self.assertEqual(log.status_sent, 'confirmed')

    def test_staff_notification_requires_staff_and_matches_order_status(self):
        response = self.client.post(
            f'/staff/order/{self.order.pk}/log-wa/confirmed/',
        )
        self.assertRedirects(
            response,
            f'/admin/login/?next=%2Fstaff%2Forder%2F{self.order.pk}%2Flog-wa%2Fconfirmed%2F',
        )
        self.client.force_login(self.staff)
        response = self.client.post(
            f'/staff/order/{self.order.pk}/log-wa/packed/',
        )
        self.assertEqual(response.status_code, 409)
        response = self.client.post(
            f'/staff/order/{self.order.pk}/log-wa/cancelled/',
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(WhatsAppNotificationLog.objects.exists())

    def test_customer_order_pages_include_configured_whatsapp_contact(self):
        session = self.client.session
        session['customer_id'] = self.customer.pk
        session.save()

        detail_response = self.client.get(
            f'/my-orders/{self.order.pk}/',
        )
        self.assertContains(detail_response, 'WhatsApp Us')
        self.assertContains(detail_response, 'https://wa.me/256770000000?text=')
        self.assertContains(detail_response, 'order%20%231')

        success_response = self.client.get(
            f'/order/success/{self.order.pk}/',
        )
        self.assertContains(success_response, 'WhatsApp Us')
        self.assertContains(success_response, 'https://wa.me/256770000000?text=')


class StaffOrderPushNotificationTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username='push-order-staff',
            password='test-password',
            is_staff=True,
        )
        self.customer = Customer.objects.create(
            phone_number='0707654321',
            name='Push Customer',
        )
        self.order = Order.objects.create(
            customer=self.customer,
            status='new',
            total_amount=Decimal('12500.00'),
        )
        self.subscription = PushSubscription.objects.create(
            customer=self.customer,
            endpoint='https://push.example.test/subscription/order-update',
            p256dh='public-key',
            auth='auth-secret',
        )
        self.client.force_login(self.staff)
        self.push_settings = self.settings(
            VAPID_PRIVATE_KEY='test-private-key',
            VAPID_ADMIN_EMAIL='admin@ggmstore.com',
        )
        self.push_settings.enable()
        self.addCleanup(self.push_settings.disable)

    @patch('marketplace.views.webpush')
    def test_confirming_order_sends_confirmation_push(self, mock_webpush):
        response = self.client.post(
            f'/staff/order/{self.order.pk}/action/',
            {'action': 'confirm', 'payment_method': 'momo'},
        )

        self.assertRedirects(response, f'/staff/order/{self.order.pk}/')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'confirmed')
        self.assertEqual(self.order.payment_method, 'momo')
        mock_webpush.assert_called_once()
        args = mock_webpush.call_args.kwargs
        self.assertEqual(args['subscription_info']['endpoint'], self.subscription.endpoint)
        self.assertEqual(
            json.loads(args['data']),
            {
                'title': 'Order Confirmed!',
                'body': (
                    f'Hi Push Customer, your order #{self.order.pk} has been '
                    'confirmed and is being packed.'
                ),
                'url': f'/my-orders/{self.order.pk}/',
            },
        )
        self.assertEqual(args['vapid_private_key'], 'test-private-key')
        self.assertEqual(
            args['vapid_claims'],
            {'sub': 'mailto:admin@ggmstore.com'},
        )

    @patch('marketplace.views.webpush')
    def test_packing_order_sends_on_the_way_push(self, mock_webpush):
        self.order.status = 'confirmed'
        self.order.save(update_fields=['status'])

        response = self.client.post(
            f'/staff/order/{self.order.pk}/action/',
            {'action': 'packed'},
        )

        self.assertRedirects(response, f'/staff/order/{self.order.pk}/')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'packed')
        mock_webpush.assert_called_once()
        payload = json.loads(mock_webpush.call_args.kwargs['data'])
        self.assertEqual(payload['title'], 'Order is on the way! 🚚')
        self.assertEqual(
            payload['body'],
            f'Your order #{self.order.pk} is out for delivery. '
            'Please have UGX 12,500 ready.',
        )
        self.assertEqual(payload['url'], f'/my-orders/{self.order.pk}/')

    @patch('marketplace.views.webpush')
    def test_missing_subscription_does_not_prevent_order_confirmation(
        self,
        mock_webpush,
    ):
        self.subscription.delete()

        response = self.client.post(
            f'/staff/order/{self.order.pk}/action/',
            {'action': 'confirm', 'payment_method': 'cash'},
        )

        self.assertRedirects(response, f'/staff/order/{self.order.pk}/')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'confirmed')
        mock_webpush.assert_not_called()

    @patch('marketplace.views.webpush')
    def test_expired_subscription_is_removed_without_failing_order_action(
        self,
        mock_webpush,
    ):
        expired_response = Response()
        expired_response.status_code = 410
        mock_webpush.side_effect = WebPushException(
            'Subscription expired',
            response=expired_response,
        )

        response = self.client.post(
            f'/staff/order/{self.order.pk}/action/',
            {'action': 'confirm', 'payment_method': 'cash'},
        )

        self.assertRedirects(response, f'/staff/order/{self.order.pk}/')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'confirmed')
        self.assertFalse(
            PushSubscription.objects.filter(pk=self.subscription.pk).exists()
        )

    @patch('marketplace.views.webpush')
    def test_push_service_failure_does_not_fail_order_action(self, mock_webpush):
        failed_response = Response()
        failed_response.status_code = 503
        mock_webpush.side_effect = WebPushException(
            'Push service unavailable',
            response=failed_response,
        )

        response = self.client.post(
            f'/staff/order/{self.order.pk}/action/',
            {'action': 'confirm', 'payment_method': 'cash'},
        )

        self.assertRedirects(response, f'/staff/order/{self.order.pk}/')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'confirmed')
        self.assertTrue(
            PushSubscription.objects.filter(pk=self.subscription.pk).exists()
        )

    @patch('marketplace.views.webpush')
    def test_delivery_and_cancellation_do_not_send_pushes(self, mock_webpush):
        self.order.status = 'packed'
        self.order.save(update_fields=['status'])
        self.client.post(
            f'/staff/order/{self.order.pk}/action/',
            {'action': 'delivered'},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'delivered')
        mock_webpush.assert_not_called()

        self.order.status = 'new'
        self.order.save(update_fields=['status'])
        self.client.post(
            f'/staff/order/{self.order.pk}/action/',
            {'action': 'cancel'},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'cancelled')
        mock_webpush.assert_not_called()


class PushSubscriptionTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            phone_number='0707654321',
            name='Push Customer',
        )
        session = self.client.session
        session['customer_id'] = self.customer.pk
        session.save()
        self.subscription_data = {
            'endpoint': 'https://push.example.test/subscription/unique',
            'keys': {
                'p256dh': 'public-key',
                'auth': 'auth-secret',
            },
        }
        self.subscribe_url = reverse('save_push_subscription')

    def test_subscription_is_saved_for_current_customer(self):
        response = self.client.post(
            self.subscribe_url,
            data=json.dumps(self.subscription_data),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        subscription = PushSubscription.objects.get()
        self.assertEqual(subscription.customer, self.customer)
        self.assertEqual(subscription.endpoint, self.subscription_data['endpoint'])
        self.assertEqual(subscription.p256dh, 'public-key')
        self.assertEqual(subscription.auth, 'auth-secret')

    def test_existing_subscription_is_updated(self):
        self.client.post(
            self.subscribe_url,
            data=json.dumps(self.subscription_data),
            content_type='application/json',
        )
        self.subscription_data['keys']['auth'] = 'new-auth-secret'
        response = self.client.post(
            self.subscribe_url,
            data=json.dumps(self.subscription_data),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(PushSubscription.objects.count(), 1)
        self.assertEqual(
            PushSubscription.objects.get().auth,
            'new-auth-secret',
        )

    def test_invalid_subscription_payload_is_rejected(self):
        invalid_payloads = (
            ('{invalid json', 'application/json'),
            (json.dumps({'endpoint': 'https://push.example.test/no-keys'}), 'application/json'),
            (
                json.dumps({
                    **self.subscription_data,
                    'endpoint': 'http://push.example.test/insecure',
                }),
                'application/json',
            ),
            (json.dumps(self.subscription_data), 'text/plain'),
        )

        for payload, content_type in invalid_payloads:
            with self.subTest(content_type=content_type, payload=payload[:20]):
                response = self.client.post(
                    self.subscribe_url,
                    data=payload,
                    content_type=content_type,
                )
                self.assertIn(response.status_code, {400, 415})
        self.assertFalse(PushSubscription.objects.exists())

    def test_subscription_endpoint_requires_post_and_csrf(self):
        response = self.client.get(self.subscribe_url)
        self.assertEqual(response.status_code, 405)

        csrf_client = self.client_class(enforce_csrf_checks=True)
        response = csrf_client.post(
            self.subscribe_url,
            data=json.dumps(self.subscription_data),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    def test_home_renders_push_prompt_when_public_key_is_configured(self):
        with self.settings(VAPID_PUBLIC_KEY='public-vapid-key'):
            response = self.client.get(reverse('home'))

        self.assertContains(response, 'name="vapid-public-key"')
        self.assertContains(response, 'public-vapid-key')
        self.assertContains(response, 'Get order updates')
        self.assertContains(response, 'push-subscription-url')

    @patch('marketplace.management.commands.send_test_push.webpush')
    def test_test_push_command_sends_to_all_subscriptions(self, mock_webpush):
        PushSubscription.objects.create(
            customer=self.customer,
            endpoint=self.subscription_data['endpoint'],
            p256dh='public-key',
            auth='auth-secret',
        )
        output = StringIO()

        with self.settings(
            VAPID_PRIVATE_KEY='test-private-key',
            VAPID_ADMIN_EMAIL='admin@ggmstore.com',
        ):
            call_command('send_test_push', stdout=output)

        self.assertIn('Sent: 1, Failed: 0', output.getvalue())
        mock_webpush.assert_called_once()
        self.assertEqual(
            mock_webpush.call_args.kwargs['subscription_info']['endpoint'],
            self.subscription_data['endpoint'],
        )

    @patch('marketplace.management.commands.send_test_push.webpush')
    def test_test_push_command_removes_gone_subscriptions(self, mock_webpush):
        subscription = PushSubscription.objects.create(
            customer=self.customer,
            endpoint=self.subscription_data['endpoint'],
            p256dh='public-key',
            auth='auth-secret',
        )
        expired_response = Response()
        expired_response.status_code = 410
        mock_webpush.side_effect = WebPushException(
            'Subscription expired',
            response=expired_response,
        )
        output = StringIO()

        with self.settings(
            VAPID_PRIVATE_KEY='test-private-key',
            VAPID_ADMIN_EMAIL='admin@ggmstore.com',
        ), self.assertRaises(CommandError):
            call_command('send_test_push', stdout=output)

        self.assertFalse(PushSubscription.objects.filter(pk=subscription.pk).exists())
        self.assertIn('Removed expired subscription', output.getvalue())


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


class StoreStatusTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username='store-status-staff',
            password='test-password',
            is_staff=True,
        )
        self.customer = Customer.objects.create(phone_number='0709876543')
        self.group = ProductGroup.objects.create(name='Test Group')
        self.product = Product.objects.create(
            code='STORE001',
            name='Store Status Product',
            group=self.group,
            selling_price=Decimal('1000.00'),
        )
        self.config = StoreConfig.objects.create()
        session = self.client.session
        session['cart'] = {str(self.product.pk): 1}
        session.save()

    def test_staff_can_toggle_store_status_via_post(self):
        self.client.force_login(self.staff)

        response = self.client.post('/staff/toggle-store/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Store is currently CLOSED')
        self.config.refresh_from_db()
        self.assertFalse(self.config.is_open)

        response = self.client.post('/staff/toggle-store/')
        self.assertContains(response, 'Store is currently OPEN')
        self.config.refresh_from_db()
        self.assertTrue(self.config.is_open)

    def test_non_staff_cannot_toggle_store_status(self):
        user = get_user_model().objects.create_user(
            username='store-status-customer',
            password='test-password',
        )
        self.client.force_login(user)

        response = self.client.post('/staff/toggle-store/')

        self.assertRedirects(
            response,
            '/admin/login/?next=%2Fstaff%2Ftoggle-store%2F',
        )
        self.config.refresh_from_db()
        self.assertTrue(self.config.is_open)

    def test_closed_store_blocks_cart_add_checkout_and_disables_controls(self):
        self.config.is_open = False
        self.config.closed_message = 'Closed for maintenance.'
        self.config.save()

        home_response = self.client.get('/?q=STORE001')
        self.assertContains(home_response, 'We are currently closed')
        self.assertContains(home_response, 'Closed for maintenance.')
        self.assertContains(home_response, 'disabled')
        self.assertContains(home_response, 'Closed')
        self.assertNotContains(home_response, 'hx-post="/cart/add/')

        group_response = self.client.get(f'/group/{self.group.pk}/')
        self.assertContains(group_response, 'disabled')
        self.assertContains(group_response, 'Closed')

        cart_response = self.client.get('/cart/')
        self.assertContains(cart_response, 'Store is Closed')
        self.assertNotContains(cart_response, 'href="/checkout/"')

        add_response = self.client.post(f'/cart/add/{self.product.pk}/')
        self.assertEqual(add_response.status_code, 403)
        self.assertEqual(self.client.session['cart'], {str(self.product.pk): 1})

        checkout_response = self.client.get('/checkout/', follow=True)
        self.assertEqual(checkout_response.redirect_chain, [('/cart/', 302)])
        self.assertContains(checkout_response, 'Closed for maintenance.')
        checkout_post_response = self.client.post('/checkout/', {
            'phone': '0709876543',
            'apartment': '',
            'payment_method': 'cash',
        })
        self.assertEqual(checkout_post_response.status_code, 302)
        self.assertEqual(Order.objects.count(), 0)

        cart_update_response = self.client.post(
            f'/cart/update/{self.product.pk}/',
            {'action': 'inc'},
        )
        self.assertEqual(cart_update_response.status_code, 403)
        self.assertEqual(self.client.session['cart'], {str(self.product.pk): 1})

    def test_staff_orders_shows_store_status_banner(self):
        self.client.force_login(self.staff)

        response = self.client.get('/staff/')

        self.assertContains(response, 'Store is currently OPEN')
        self.assertContains(response, 'hx-post="/staff/toggle-store/"')
