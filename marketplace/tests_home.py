"""Tests for the shop-style home page. Run with:  python manage.py test marketplace.tests_home"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Customer, Order, OrderItem, Product, ProductGroup, Shelf, ShelfItem, StoreConfig
from .shelves import (
    MIN_SHELF_ITEMS, build_items, categories_with_counts, discover_page, get_config, home_categories,
    home_shelves, interleave_by_group, sellable_products, seed_default_shelves, shelf_items,
)

# Pages that extend base.html use {% static %}; see the note in tests_qr.py.
PLAIN_STATIC = override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})

_counter = {'n': 0}


def make_product(name=None, price=1000, stock=10, group=None, parent=None, label=None, photo=True, **extra):
    _counter['n'] += 1
    n = _counter['n']
    return Product.objects.create(
        code=f'P{n:05d}', name=name or f'Product {n}', selling_price=Decimal(price), stock_quantity=Decimal(stock),
        group=group, parent_group=parent, variant_label=label,
        image=f'products/p{n}.jpg' if photo else '', **extra,
    )


def make_many(count, **kwargs):
    return [make_product(**kwargs) for _ in range(count)]


def sell(product, quantity=1, status='delivered', days_ago=0):
    customer, _ = Customer.objects.get_or_create(phone_number='0700000999')
    order = Order.objects.create(customer=customer, status=status, total_amount=Decimal('1000'))
    OrderItem.objects.create(order=order, product=product, quantity=Decimal(quantity), price_at_time_of_order=product.selling_price)
    if days_ago:
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
    return order


class EligibilityTests(TestCase):
    def test_only_buyable_products_are_sellable(self):
        good = make_product()
        make_product(stock=0)
        make_product(manually_disabled=True)
        make_product(is_active=False)
        make_product(price=0)
        self.assertEqual(list(sellable_products()), [good])

    def test_photo_rule_can_be_switched_off(self):
        shelf = Shelf.objects.create(title='Cheap', kind=Shelf.UNDER_PRICE, max_price=Decimal('5000'))
        make_many(3, photo=True)
        make_many(3, photo=False)
        config = get_config()
        self.assertTrue(config.shelves_require_photo)
        self.assertEqual(len(shelf_items(shelf, config)), 3)
        config.shelves_require_photo = False
        self.assertEqual(len(shelf_items(shelf, config)), 6)


class ShelfKindTests(TestCase):
    def test_curated_shelf_keeps_the_order_you_set(self):
        shelf = Shelf.objects.create(title='Essentials', kind=Shelf.CURATED)
        milk, bread, eggs = make_product(name='Milk'), make_product(name='Bread'), make_product(name='Eggs')
        ShelfItem.objects.create(shelf=shelf, product=eggs, position=1)
        ShelfItem.objects.create(shelf=shelf, product=milk, position=2)
        ShelfItem.objects.create(shelf=shelf, product=bread, position=3)
        names = [item['product'].name for item in shelf_items(shelf, get_config())]
        self.assertEqual(names, ['Eggs', 'Milk', 'Bread'])

    def test_category_shelf_lists_best_sellers_first(self):
        group = ProductGroup.objects.create(name='Drinks')
        other = ProductGroup.objects.create(name='Soap')
        slow, fast, unrelated = make_product(name='Slow', group=group), make_product(name='Fast', group=group), make_product(group=other)
        sell(fast, 5)
        sell(slow, 1)
        sell(unrelated, 50)
        shelf = Shelf.objects.create(title='Drinks', kind=Shelf.CATEGORY, group=group)
        self.assertEqual([i['product'].name for i in shelf_items(shelf, get_config())], ['Fast', 'Slow'])

    def test_under_price_only_includes_cheap_products(self):
        cheap, pricey = make_product(price=2500), make_product(price=9000)
        shelf = Shelf.objects.create(title='Cheap', kind=Shelf.UNDER_PRICE, max_price=Decimal('3000'))
        self.assertEqual([i['product'] for i in shelf_items(shelf, get_config())], [cheap])

    def test_new_arrivals_only_shows_products_really_added_recently(self):
        recent = make_product(name='Recent')
        old = make_product(name='Old')
        Product.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=30))
        legacy = make_product(name='Legacy')
        Product.objects.filter(pk=legacy.pk).update(created_at=None)   # added before the field existed
        shelf = Shelf.objects.create(title='New', kind=Shelf.NEW)
        self.assertEqual([i['product'].name for i in shelf_items(shelf, get_config())], ['Recent'])

    def test_popular_counts_only_recent_non_cancelled_sales(self):
        hot, old_hit, cancelled, never = make_product(name='Hot'), make_product(name='OldHit'), make_product(name='Cancelled'), make_product(name='Never')
        sell(hot, 3)
        sell(old_hit, 9, days_ago=40)
        sell(cancelled, 9, status='cancelled')
        shelf = Shelf.objects.create(title='Popular', kind=Shelf.POPULAR)
        self.assertEqual([i['product'].name for i in shelf_items(shelf, get_config())], ['Hot'])

    def test_misconfigured_shelves_are_empty_not_broken(self):
        make_product()
        for shelf in (Shelf(title='a', kind=Shelf.CATEGORY), Shelf(title='b', kind=Shelf.UNDER_PRICE), Shelf(title='c', kind='bogus')):
            self.assertEqual(shelf_items(shelf, get_config()), [])


class FamilyTests(TestCase):
    def test_variants_become_one_card_with_a_from_price(self):
        kg1 = make_product(name='Sugar 1KG', price=5000, parent='Kakira Sugar', label='1KG')
        make_product(name='Sugar 2KG', price=9500, parent='Kakira Sugar', label='2KG', photo=False)
        make_product(name='Sugar 5KG', price=22000, parent='Kakira Sugar', label='5KG')
        items = build_items(list(sellable_products().order_by('id')), sellable_products(), 10)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertTrue(item['is_group'])
        self.assertEqual((item['variant_count'], item['min_price'], item['max_price']), (3, Decimal('5000'), Decimal('22000')))
        self.assertEqual(item['product'], kg1)
        self.assertEqual(item['parent_name'], 'Kakira Sugar')

    def test_group_card_uses_the_first_variant_that_has_a_photo(self):
        make_product(name='Rice 500G', price=2000, parent='Rice', photo=False)
        with_photo = make_product(name='Rice 1KG', price=3500, parent='Rice')
        shelf = Shelf.objects.create(title='All', kind=Shelf.UNDER_PRICE, max_price=Decimal('99999'))
        config = get_config()
        config.shelves_require_photo = False
        item = build_items(list(sellable_products().order_by('selling_price')), sellable_products(), 5)[0]
        self.assertEqual(item['image_product'], with_photo)

    def test_one_available_variant_is_shown_as_a_plain_product(self):
        make_product(name='Soap A', parent='Soap', label='A')
        make_product(name='Soap B', parent='Soap', label='B', stock=0)   # sold out: not counted
        item = build_items(list(sellable_products()), sellable_products(), 5)[0]
        self.assertFalse(item['is_group'])

    def test_a_family_takes_the_place_of_its_best_ranked_member(self):
        a, b = make_product(name='A'), make_product(name='C')
        sugar1 = make_product(name='Sugar 1', parent='Sugar')
        sugar2 = make_product(name='Sugar 2', parent='Sugar')
        rows = [a, sugar2, b, sugar1]
        names = [(i.get('parent_name') or i['product'].name) for i in build_items(rows, sellable_products(), 10)]
        self.assertEqual(names, ['A', 'Sugar', 'C'])


class ShelvesOnHomeTests(TestCase):
    def test_a_shelf_needs_enough_products_to_appear(self):
        shelf = Shelf.objects.create(title='Cheap', kind=Shelf.UNDER_PRICE, max_price=Decimal('5000'))
        make_many(MIN_SHELF_ITEMS - 1)
        self.assertEqual(home_shelves(get_config()), [])
        make_product()
        blocks = home_shelves(get_config())
        self.assertEqual([b['shelf'] for b in blocks], [shelf])

    def test_inactive_shelves_and_position_order(self):
        make_many(8)
        second = Shelf.objects.create(title='Second', kind=Shelf.UNDER_PRICE, max_price=Decimal('5000'), position=20)
        first = Shelf.objects.create(title='First', kind=Shelf.UNDER_PRICE, max_price=Decimal('5000'), position=10)
        Shelf.objects.create(title='Hidden', kind=Shelf.UNDER_PRICE, max_price=Decimal('5000'), is_active=False)
        self.assertEqual([b['shelf'] for b in home_shelves(get_config())], [first, second])

    def test_default_shelves_are_created_once_only(self):
        config = get_config()
        seed_default_shelves(config)
        self.assertEqual(Shelf.objects.count(), 4)
        Shelf.objects.filter(title='New arrivals').delete()
        seed_default_shelves(get_config())
        self.assertEqual(Shelf.objects.count(), 3)         # not re-created after you removed one


class CategoryTests(TestCase):
    def test_pinned_categories_come_first_in_your_order(self):
        a, b, c = (ProductGroup.objects.create(name=n) for n in ('Alpha', 'Beta', 'Gamma'))
        ProductGroup.objects.filter(pk=b.pk).update(home_order=1)
        ProductGroup.objects.filter(pk=c.pk).update(home_order=2)
        self.assertEqual([g.name for g in home_categories()], ['Beta', 'Gamma'])

    def test_without_pins_the_biggest_categories_with_products_are_used(self):
        big, small, empty = (ProductGroup.objects.create(name=n) for n in ('Big', 'Small', 'Empty'))
        make_many(3, group=big)
        make_product(group=small)
        make_product(group=empty, stock=0)           # nothing to buy there
        self.assertEqual([g.name for g in home_categories()], ['Big', 'Small'])
        self.assertEqual([(g.name, g.available) for g in categories_with_counts()], [('Big', 3), ('Small', 1)])


class DiscoverTests(TestCase):
    def test_neighbours_come_from_different_categories(self):
        milk, soap = ProductGroup.objects.create(name='Milk'), ProductGroup.objects.create(name='Soap')
        rows = make_many(3, group=milk) + make_many(3, group=soap)
        mixed = interleave_by_group(rows)
        self.assertEqual([p.group_id for p in mixed], [milk.id, soap.id] * 3)

    def test_pages_have_twelve_cards_and_the_last_has_no_more(self):
        make_many(30)
        config = get_config()
        page1, more1 = discover_page(config, 1)
        page3, more3 = discover_page(config, 3)
        self.assertEqual((len(page1), more1), (12, True))
        self.assertEqual((len(page3), more3), (6, False))

    def test_best_sellers_come_first(self):
        make_many(5)
        star = make_product(name='Star')
        sell(star, 10)
        page, _ = discover_page(get_config(), 1)
        self.assertEqual(page[0]['product'], star)


@PLAIN_STATIC
class HomePageTests(TestCase):
    def test_empty_shop_shows_a_friendly_message(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Our shelves are being stocked')

    def test_shop_with_products_shows_sections(self):
        group = ProductGroup.objects.create(name='Dairy and milk', home_order=1)
        for product in make_many(8, group=group):
            pass
        products = list(Product.objects.all())
        sell(products[0], 2)
        response = self.client.get('/')
        self.assertContains(response, 'Shop by category')
        self.assertContains(response, 'Dairy and milk')
        self.assertContains(response, 'Under UGX 3,000')      # default shelf, 8 products at UGX 1,000
        self.assertContains(response, 'Discover more')
        self.assertContains(response, 'See all 1')
        self.assertEqual(Shelf.objects.count(), 4)
        # Only one product has sold, so "Popular right now" stays hidden instead of looking half empty
        self.assertNotContains(response, 'Popular right now')
        for product in products[:MIN_SHELF_ITEMS]:
            sell(product, 1)
        self.assertContains(self.client.get('/'), 'Popular right now')

    def test_closed_shop_shows_locks_not_add_buttons(self):
        make_many(6)
        StoreConfig.objects.update_or_create(pk=1, defaults={'is_open': False})
        response = self.client.get('/')
        self.assertContains(response, 'We are closed right now')
        self.assertNotContains(response, 'hx-vals=\'{"action":"inc"}\'')

    def test_search_finds_products_including_out_of_stock(self):
        make_product(name='Fresh Milk')
        make_product(name='Milk Powder', stock=0)
        make_product(name='Soap')
        response = self.client.get('/?q=milk')
        self.assertContains(response, 'Fresh Milk')
        self.assertContains(response, 'Milk Powder')
        self.assertContains(response, 'Out of stock')
        self.assertNotContains(response, 'Soap')

    def test_discover_and_other_pages_render(self):
        make_many(30)
        self.assertContains(self.client.get('/discover/?page=2'), 'hx-get')
        self.assertEqual(self.client.get('/discover/?page=abc').status_code, 200)
        self.assertEqual(self.client.get('/discover/?page=9999').status_code, 200)
        group = ProductGroup.objects.create(name='Rice and grains')
        make_product(group=group)
        response = self.client.get('/categories/')
        self.assertContains(response, 'Rice and grains')
        self.assertContains(response, '1 item')

    def test_shelf_see_all_page(self):
        make_many(6)
        shelf = Shelf.objects.create(title='Cheap stuff', kind=Shelf.UNDER_PRICE, max_price=Decimal('5000'))
        self.assertContains(self.client.get(f'/shelf/{shelf.pk}/'), 'Cheap stuff')
        Shelf.objects.filter(pk=shelf.pk).update(is_active=False)
        self.assertEqual(self.client.get(f'/shelf/{shelf.pk}/').status_code, 404)


@PLAIN_STATIC
class CardStepperTests(TestCase):
    def setUp(self):
        self.product = make_product(name='Fresh Milk', stock=3)
        self.url = f'/cart/card/{self.product.pk}/'

    def cart(self):
        return self.client.session.get('cart', {})

    def post(self, action):
        return self.client.post(self.url, {'action': action})

    def test_first_add_returns_a_stepper_and_a_toast(self):
        response = self.post('inc')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'card-ctl')
        self.assertContains(response, 'aria-live')
        self.assertIn('cartUpdated', response['HX-Trigger'])
        self.assertIn('Added: Fresh Milk', response['HX-Trigger'])
        self.assertEqual(self.cart(), {str(self.product.pk): 1})

    def test_increase_and_decrease_and_remove(self):
        self.post('inc')
        second = self.post('inc')
        self.assertNotIn('Added:', second['HX-Trigger'])          # only the first add shouts
        self.assertEqual(self.cart(), {str(self.product.pk): 2})
        self.post('dec')
        self.assertEqual(self.cart(), {str(self.product.pk): 1})
        last = self.post('dec')
        self.assertEqual(self.cart(), {})
        self.assertContains(last, 'Add Fresh Milk to cart')       # back to the plain add button

    def test_cannot_add_more_than_is_in_stock(self):
        for _ in range(3):
            self.post('inc')
        response = self.post('inc')
        self.assertEqual(response.status_code, 409)
        self.assertIn('Only 3 left', response['HX-Trigger'])
        self.assertEqual(self.cart(), {str(self.product.pk): 3})

    def test_out_of_stock_and_disabled_products_cannot_be_added(self):
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=0)
        self.assertEqual(self.post('inc').status_code, 409)
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=5, manually_disabled=True)
        self.assertEqual(self.post('inc').status_code, 409)
        self.assertEqual(self.cart(), {})

    def test_closed_store_blocks_adding_but_not_removing(self):
        self.post('inc')
        StoreConfig.objects.update_or_create(pk=1, defaults={'is_open': False})
        blocked = self.post('inc')
        self.assertEqual(blocked.status_code, 403)
        self.assertIn('closed', blocked['HX-Trigger'])
        self.assertEqual(self.post('dec').status_code, 200)

    def test_only_post_is_allowed_and_unknown_products_404(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.client.post('/cart/card/99999/', {'action': 'inc'}).status_code, 404)

    def test_cards_on_the_home_page_show_the_quantity_already_in_the_cart(self):
        make_many(5)
        self.post('inc')
        self.post('inc')
        html = self.client.get('/?q=Fresh').content.decode()
        self.assertIn('aria-label="Decrease Fresh Milk quantity"', html)
        self.assertIn('>2</span>', html)


@PLAIN_STATIC
class CartRemovalTests(TestCase):
    def setUp(self):
        StoreConfig.objects.create(
            delivery_fee=Decimal('2000.00'),
            free_delivery_threshold=Decimal('35000.00'),
            minimum_order_value=Decimal('0.00'),
        )
        self.product = make_product(name='Fresh Milk')
        session = self.client.session
        session['cart'] = {str(self.product.pk): 10}
        session.save()

    def test_cart_item_has_a_direct_remove_button(self):
        response = self.client.get('/cart/')

        self.assertContains(response, f'hx-post="/cart/update/{self.product.pk}/"')
        self.assertContains(response, 'hx-vals=\'{"action":"remove"}\'')
        self.assertContains(response, 'aria-label="Remove Fresh Milk from cart"')

    def test_direct_remove_action_removes_the_entire_item(self):
        response = self.client.post(
            f'/cart/update/{self.product.pk}/',
            {'action': 'remove'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session['cart'], {})
        self.assertContains(response, 'Your cart is empty')
        self.assertEqual(response['HX-Trigger'], 'cartUpdated')


@PLAIN_STATIC
class StaffPhotoListTests(TestCase):
    def test_login_required_and_best_sellers_listed_first(self):
        self.assertEqual(self.client.get('/staff/photos/').status_code, 302)
        quiet, popular = make_product(name='Quiet', photo=False), make_product(name='Popular', photo=False)
        make_product(name='Has photo', photo=True)
        sell(popular, 7)
        staff = get_user_model().objects.create_user('s', password='p')
        self.client.force_login(staff)
        response = self.client.get('/staff/photos/')
        names = [p.name for p in response.context['products']]
        self.assertEqual(names, ['Popular', 'Quiet'])
        self.assertEqual((response.context['total'], response.context['missing'], response.context['with_photo']), (3, 2, 1))


@PLAIN_STATIC
class AdminSmokeTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('boss', 'b@example.com', 'pw')
        self.client.force_login(self.admin)

    def test_admin_pages_open(self):
        make_many(5)
        Shelf.objects.create(title='Cheap', kind=Shelf.UNDER_PRICE, max_price=Decimal('5000'))
        ProductGroup.objects.create(name='Dairy')
        for path in (
            '/admin/marketplace/shelf/', '/admin/marketplace/shelf/add/', '/admin/marketplace/productgroup/',
            '/admin/marketplace/product/', '/admin/marketplace/product/?has_photo=no', '/admin/marketplace/product/?has_photo=yes',
        ):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertContains(self.client.get('/admin/marketplace/shelf/'), 'Yes, 5 products')