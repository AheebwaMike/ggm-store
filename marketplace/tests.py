from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import Customer, Order, OrderItem, Product


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
