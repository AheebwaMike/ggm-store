"""Tests for proposing and creating product families. Run with:  python manage.py test marketplace.tests_families"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .family_suggestions import normalise, pretty, split_name, suggest_families
from .models import Family, FamilyDismissal, Product, ProductGroup

PLAIN_STATIC = override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})

_counter = {'n': 0}


def make(name, price=1000, group=None, parent=None, label=None, **extra):
    _counter['n'] += 1
    return Product.objects.create(
        code=f'F{_counter["n"]:05d}', name=name, selling_price=Decimal(price), stock_quantity=Decimal(10),
        group=group, parent_group=parent, variant_label=label, **extra,
    )


class NameSplittingTests(TestCase):
    def test_sizes_are_split_from_the_name(self):
        cases = {
            'KAKIRA SUGAR 1KG': ('KAKIRA SUGAR', '1KG'),
            'Kakira Sugar 500 g': ('Kakira Sugar', '500G'),
            'COKE 1.5 LTR': ('COKE', '1.5LTR'),
            'COKE 1,5L': ('COKE', '1.5L'),
            'SODA 500ML X 12': ('SODA', '500ML X12'),
            'MILK 6 PCS': ('MILK', '6PCS'),
            'RICE - 2KG': ('RICE', '2KG'),
            'FLOUR (2KG)': ('FLOUR', '2KG'),
            'SUGAR 1KG BROWN': ('SUGAR BROWN', '1KG'),
            'EXERCISE BOOK 96 PAGES': ('EXERCISE BOOK', '96PAGES'),
        }
        for name, expected in cases.items():
            self.assertEqual(split_name(name), expected, name)

    def test_names_without_a_size_are_left_alone(self):
        for name in ('BIC PEN BLUE', 'FANTA 7UP', 'AXE', 'TOMATO PASTE'):
            self.assertEqual(split_name(name), (name, ''), name)

    def test_helpers(self):
        self.assertEqual(normalise('  Kakira  SUGAR! '), 'kakira sugar')
        self.assertEqual(pretty("FARMER'S CHOICE"), "Farmer's Choice")


class SuggestionTests(TestCase):
    def names(self, suggestions=None):
        return {s['name']: s for s in (suggestions if suggestions is not None else suggest_families())}

    def test_sizes_of_the_same_product_are_suggested_together(self):
        make('KAKIRA SUGAR 5KG', 22000)
        make('KAKIRA SUGAR 1KG', 5000)
        make('KAKIRA SUGAR 2KG', 9500)
        make('LONE SALT 1KG')
        suggestions = suggest_families()
        self.assertEqual(len(suggestions), 1)
        suggestion = suggestions[0]
        self.assertEqual((suggestion['name'], suggestion['confidence'], suggestion['kind_guess']), ('Kakira Sugar', 'sizes', 'size'))
        self.assertEqual([m['label'] for m in suggestion['members']], ['1KG', '2KG', '5KG'])     # cheapest first
        self.assertFalse(suggestion['existing'])

    def test_products_in_different_categories_are_not_mixed(self):
        a, b = ProductGroup.objects.create(name='Food'), ProductGroup.objects.create(name='Pets')
        make('SUGAR 1KG', group=a)
        make('SUGAR 2KG', group=b)
        self.assertEqual(suggest_families(), [])

    def test_two_products_with_the_same_label_are_not_suggested(self):
        make('RICE 1KG')
        make('Rice 1kg')
        self.assertEqual(suggest_families(), [])

    def test_flavours_sharing_the_first_words_are_suggested_for_checking(self):
        make('BIC PEN BLUE')
        make('BIC PEN BLACK')
        make('BIC PEN RED')
        suggestion = suggest_families()[0]
        self.assertEqual((suggestion['name'], suggestion['confidence'], suggestion['kind_guess']), ('Bic Pen', 'check', ''))
        self.assertEqual(sorted(m['label'] for m in suggestion['members']), ['Black', 'Blue', 'Red'])

    def test_flavours_of_the_same_size_are_suggested_for_checking(self):
        make('FRESH DAIRY YOGHURT 500ML STRAWBERRY')
        make('FRESH DAIRY YOGHURT 500ML VANILLA')
        make('FRESH DAIRY YOGHURT 500ML MANGO')
        suggestions = suggest_families()
        self.assertEqual(len(suggestions), 1)
        suggestion = suggestions[0]
        self.assertEqual((suggestion['name'], suggestion['confidence']), ('Fresh Dairy Yoghurt 500ML', 'check'))
        self.assertEqual(sorted(m['label'] for m in suggestion['members']), ['Mango', 'Strawberry', 'Vanilla'])

    def test_products_with_two_choices_get_the_clearer_suggestion_first(self):
        # Vanilla comes in two sizes AND yoghurt comes in several flavours: the data fits both ways.
        make('FRESH DAIRY YOGHURT 500ML STRAWBERRY')
        make('FRESH DAIRY YOGHURT 500ML VANILLA')
        make('FRESH DAIRY YOGHURT 500ML MANGO')
        make('FRESH DAIRY YOGHURT 250ML VANILLA')
        first = suggest_families()[0]
        self.assertEqual((first['name'], first['confidence']), ('Fresh Dairy Yoghurt Vanilla', 'sizes'))
        self.assertEqual(sorted(m['label'] for m in first['members']), ['250ML', '500ML'])

    def test_a_single_shared_first_word_is_not_enough(self):
        make('FRESH MILK')
        make('FRESH CREAM')
        make('COCA COLA')
        make('COCA FANTA')
        self.assertEqual(suggest_families(), [])

    def test_already_grouped_inactive_and_unpriced_products_are_ignored(self):
        make('TEA 100G', parent='Tea', label='100G')
        make('TEA 250G', parent='Tea', label='250G')
        make('COFFEE 100G', is_active=False)
        make('COFFEE 200G')
        make('JAM 250G', price=0)
        make('JAM 500G')
        self.assertEqual(suggest_families(), [])

    def test_a_new_product_is_offered_for_an_existing_family(self):
        make('TEA 100G', parent='Rwenzori Tea', label='100G')
        make('TEA 250G', parent='Rwenzori Tea', label='250G')
        make('RWENZORI TEA 500G', 9000)
        suggestion = suggest_families()[0]
        self.assertTrue(suggestion['existing'])
        self.assertEqual((suggestion['name'], suggestion['existing_count']), ('Rwenzori Tea', 2))
        self.assertEqual([m['label'] for m in suggestion['members']], ['500G'])

    def test_dismissed_suggestions_stay_away(self):
        make('OIL 1L')
        make('OIL 3L')
        key = suggest_families()[0]['key']
        FamilyDismissal.objects.create(key=key)
        self.assertEqual(suggest_families(), [])

    def test_sizes_come_before_flavours_and_bigger_families_first(self):
        make('BIC PEN BLUE')
        make('BIC PEN BLACK')
        for label in ('1KG', '2KG'):
            make(f'AAA RICE {label}')
        for label in ('1KG', '2KG', '5KG'):
            make(f'ZZZ SUGAR {label}')
        self.assertEqual([s['name'] for s in suggest_families()], ['Zzz Sugar', 'Aaa Rice', 'Bic Pen'])


@PLAIN_STATIC
class FamilyScreenTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user('staff', password='pw')
        self.client.force_login(self.staff)
        self.sugar = [make(f'KAKIRA SUGAR {label}', price) for label, price in (('1KG', 5000), ('2KG', 9500), ('5KG', 22000))]

    def accept(self, products=None, name='Kakira Sugar', labels=None, kind='size', existing='0', key='0:kakira sugar'):
        products = self.sugar if products is None else products
        data = {'key': key, 'existing': existing, 'family_name': name, 'kind': kind}
        data['member'] = [p.pk for p in products]
        data['use'] = [p.pk for p in products]
        for product, label in zip(products, labels or ['1KG', '2KG', '5KG']):
            data[f'label_{product.pk}'] = label
        return self.client.post('/staff/families/accept/', data)

    def test_login_required_and_post_only(self):
        self.client.logout()
        for path in ('/staff/families/', '/staff/families/accept/', '/staff/families/dismiss/', '/staff/families/undo/'):
            self.assertEqual(self.client.get(path).status_code, 302, path)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get('/staff/families/accept/').status_code, 405)

    def test_page_lists_suggestions_with_editable_labels(self):
        response = self.client.get('/staff/families/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Kakira Sugar')
        self.assertContains(response, 'Group these')
        self.assertContains(response, 'Not a family')
        self.assertContains(response, 'value="1KG"')
        self.assertContains(response, '1 possible family found')

    def test_empty_page_is_friendly(self):
        Product.objects.all().delete()
        self.assertContains(self.client.get('/staff/families/'), 'No suggestions right now')

    def test_grouping_sets_name_labels_and_kind(self):
        response = self.accept()
        self.assertContains(response, 'Grouped 3 products')
        self.assertTrue(Family.objects.filter(name='Kakira Sugar').exists())
        for product, label in zip(self.sugar, ['1KG', '2KG', '5KG']):
            product.refresh_from_db()
            self.assertEqual((product.parent_group, product.variant_label, product.variant_kind), ('Kakira Sugar', label, 'size'))
        self.assertEqual(suggest_families(), [])          # no longer suggested

    def test_the_new_family_shows_as_one_card_with_a_kind_label(self):
        self.accept()
        self.assertContains(self.client.get('/?q=sugar'), '3 sizes')

    def test_labels_can_be_edited_before_grouping(self):
        self.accept(labels=['1 Kg bag', 'Two kilos', '5 Kg sack'], kind='')
        self.assertEqual(Product.objects.get(pk=self.sugar[1].pk).variant_label, 'Two kilos')

    def test_validation_messages_keep_the_staff_members_edits(self):
        cases = [
            (dict(name='  '), 'Give the family a name.'),
            (dict(kind='colour'), 'Choose one of the kinds'),
            (dict(labels=['1KG', '', '5KG']), 'needs a label'),
            (dict(labels=['1KG', '1kg', '5KG']), 'same label'),
            (dict(labels=['1KG', 'x' * 51, '5KG']), 'too long'),
            (dict(products=self.sugar[:1], labels=['1KG']), 'at least two'),
        ]
        for kwargs, message in cases:
            response = self.accept(**kwargs)
            self.assertContains(response, message)
            self.assertContains(response, 'Group these')                     # the card is shown again
        self.assertFalse(Product.objects.filter(parent_group__isnull=False).exclude(parent_group='').exists())

    def test_existing_family_name_is_reused_ignoring_capitals_and_checks_label_clashes(self):
        make('TEA 100G', parent='Rwenzori Tea', label='100G')
        new = make('RWENZORI TEA 100G')
        clash = self.accept(products=[new], name='rwenzori tea', labels=['100g'], key='0:rwenzori tea')
        self.assertContains(clash, 'already has an option')
        ok = self.accept(products=[new], name='rwenzori TEA', labels=['500G'], key='0:rwenzori tea')
        self.assertContains(ok, 'into the existing family')
        new.refresh_from_db()
        self.assertEqual((new.parent_group, new.variant_label), ('Rwenzori Tea', '500G'))

    def test_products_grouped_by_someone_else_in_the_meantime_are_skipped(self):
        Product.objects.filter(pk=self.sugar[0].pk).update(parent_group='Other', variant_label='X')
        response = self.accept()
        self.assertContains(response, 'Grouped 2 products')
        self.assertContains(response, '1 skipped')
        self.assertEqual(Product.objects.get(pk=self.sugar[0].pk).parent_group, 'Other')

    def test_dismiss_removes_the_suggestion_for_good(self):
        response = self.client.post('/staff/families/dismiss/', {'key': '0:kakira sugar'})
        self.assertEqual(response.content, b'')
        self.assertTrue(FamilyDismissal.objects.filter(key='0:kakira sugar').exists())
        self.client.post('/staff/families/dismiss/', {'key': ''})
        self.client.post('/staff/families/dismiss/', {'key': 'no colon'})
        self.assertEqual(FamilyDismissal.objects.count(), 1)
        self.assertContains(self.client.get('/staff/families/'), 'No suggestions right now')

    def undo_data(self, done_response, name='Kakira Sugar'):
        """The Undo request the browser would send: every hidden field in the green card."""
        import re
        html = done_response.content.decode()
        fields = re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', html)
        data = {}
        for field, value in fields:
            data.setdefault(field, []).append(value)
        return {key: (values if key == 'id' else values[0]) for key, values in data.items()}

    def test_undo_restores_the_previous_values(self):
        Product.objects.filter(pk=self.sugar[0].pk).update(variant_label='old label', variant_kind='')
        done = self.accept()
        self.assertContains(done, 'Undo')
        response = self.client.post('/staff/families/undo/', self.undo_data(done))
        self.assertContains(response, 'Undone: 3 products')
        first = Product.objects.get(pk=self.sugar[0].pk)
        self.assertEqual((first.parent_group, first.variant_label, first.variant_kind), (None, 'old label', ''))
        self.assertEqual(Product.objects.get(pk=self.sugar[1].pk).variant_label, None)
        self.assertEqual(len(suggest_families()), 1)      # suggested again

    def test_undo_puts_back_empty_text_and_missing_values_exactly(self):
        Product.objects.filter(pk=self.sugar[0].pk).update(parent_group='', variant_label='')      # empty text, not NULL
        Product.objects.filter(pk=self.sugar[1].pk).update(parent_group=None, variant_label=None)
        done = self.accept()
        self.client.post('/staff/families/undo/', self.undo_data(done))
        first, second = (Product.objects.get(pk=p.pk) for p in self.sugar[:2])
        self.assertEqual((first.parent_group, first.variant_label), ('', ''))
        self.assertEqual((second.parent_group, second.variant_label), (None, None))

    # ---- editing product names while grouping ----
    def accept_with_names(self, names, products=None, **kwargs):
        products = self.sugar if products is None else products
        data = {'key': '0:kakira sugar', 'existing': '0', 'family_name': kwargs.get('name', 'Kakira Sugar'), 'kind': 'size'}
        data['member'] = [p.pk for p in products]
        data['use'] = [p.pk for p in products]
        for product, label, name in zip(products, ['1KG', '2KG', '5KG'], names):
            data[f'label_{product.pk}'] = label
            if name is not None:
                data[f'name_{product.pk}'] = name
        return self.client.post('/staff/families/accept/', data)

    def test_page_shows_editable_names_and_the_two_helper_buttons(self):
        response = self.client.get('/staff/families/')
        for product in self.sugar:
            self.assertContains(response, f'name="name_{product.pk}" value="{product.name}"')
        self.assertContains(response, 'Tidy capitals')
        self.assertContains(response, 'Name = family + label')

    def test_names_are_corrected_while_grouping(self):
        response = self.accept_with_names(['Kakira Sugar 1KG', '  Kakira   Sugar 2KG ', 'Kakira Sugar 5KG'])
        self.assertContains(response, 'Grouped 3 products')
        self.assertContains(response, '3 names corrected')
        names = [Product.objects.get(pk=p.pk).name for p in self.sugar]
        self.assertEqual(names, ['Kakira Sugar 1KG', 'Kakira Sugar 2KG', 'Kakira Sugar 5KG'])    # extra spaces collapsed

    def test_unchanged_and_missing_names_are_left_alone(self):
        response = self.accept_with_names([self.sugar[0].name, None, 'Kakira Sugar 5KG'])
        self.assertContains(response, '1 name corrected')
        self.assertEqual(Product.objects.get(pk=self.sugar[1].pk).name, 'KAKIRA SUGAR 2KG')

    def test_blank_or_overlong_names_are_refused_and_edits_are_kept(self):
        blank = self.accept_with_names(['Kakira Sugar 1KG', '   ', 'Kakira Sugar 5KG'])
        self.assertContains(blank, 'cannot be empty')
        self.assertContains(blank, 'value="Kakira Sugar 1KG"')                      # the other edits survive on the card
        long = self.accept_with_names(['Kakira Sugar 1KG', 'x' * 256, 'Kakira Sugar 5KG'])
        self.assertContains(long, 'too long')
        self.assertEqual(Product.objects.get(pk=self.sugar[0].pk).name, 'KAKIRA SUGAR 1KG')         # nothing was saved

    def test_names_of_unticked_products_are_not_changed(self):
        data = {'key': 'k:x', 'existing': '0', 'family_name': 'Kakira Sugar', 'kind': 'size',
                'member': [p.pk for p in self.sugar], 'use': [self.sugar[0].pk, self.sugar[1].pk]}
        for product, label in zip(self.sugar, ['1KG', '2KG', '5KG']):
            data[f'label_{product.pk}'] = label
            data[f'name_{product.pk}'] = 'Changed ' + label
        self.client.post('/staff/families/accept/', data)
        self.assertEqual(Product.objects.get(pk=self.sugar[2].pk).name, 'KAKIRA SUGAR 5KG')
        self.assertEqual(Product.objects.get(pk=self.sugar[0].pk).name, 'Changed 1KG')

    def test_undo_puts_the_old_names_back(self):
        done = self.accept_with_names(['Kakira Sugar 1KG', 'Kakira Sugar 2KG', 'Kakira Sugar 5KG'])
        self.client.post('/staff/families/undo/', self.undo_data(done))
        self.assertEqual([Product.objects.get(pk=p.pk).name for p in self.sugar],
                         ['KAKIRA SUGAR 1KG', 'KAKIRA SUGAR 2KG', 'KAKIRA SUGAR 5KG'])

    def test_undo_keeps_a_name_that_someone_changed_afterwards(self):
        done = self.accept_with_names(['Kakira Sugar 1KG', 'Kakira Sugar 2KG', 'Kakira Sugar 5KG'])
        Product.objects.filter(pk=self.sugar[0].pk).update(name='Edited later by someone')
        self.client.post('/staff/families/undo/', self.undo_data(done))
        self.assertEqual(Product.objects.get(pk=self.sugar[0].pk).name, 'Edited later by someone')
        self.assertEqual(Product.objects.get(pk=self.sugar[1].pk).name, 'KAKIRA SUGAR 2KG')
        self.assertIsNone(Product.objects.get(pk=self.sugar[0].pk).parent_group)           # the grouping itself is still undone

    def test_new_names_show_up_in_the_shop(self):
        self.accept_with_names(['Kakira Sugar 1KG', 'Kakira Sugar 2KG', 'Kakira Sugar 5KG'])
        make('KAKIRA SUGAR TEST DUMMY', 100)
        html = self.client.get('/product/%d/options/' % self.sugar[0].pk).content.decode()
        self.assertIn('Kakira Sugar', html)

    def test_the_same_product_ticked_twice_is_only_grouped_once(self):
        data = {'key': 'k:x', 'family_name': 'Kakira Sugar', 'kind': 'size', 'existing': '0'}
        data['member'] = [p.pk for p in self.sugar]
        data['use'] = [self.sugar[0].pk, self.sugar[0].pk, self.sugar[1].pk]
        for product, label in zip(self.sugar, ['1KG', '2KG', '5KG']):
            data[f'label_{product.pk}'] = label
        self.assertContains(self.client.post('/staff/families/accept/', data), 'Grouped 2 products')

    def test_undo_does_not_touch_products_that_moved_to_another_family(self):
        self.accept()
        Product.objects.filter(pk=self.sugar[0].pk).update(parent_group='Moved')
        data = {'family_name': 'Kakira Sugar', 'id': [self.sugar[0].pk, self.sugar[1].pk]}
        response = self.client.post('/staff/families/undo/', data)
        self.assertContains(response, 'Undone: 1 product ')
        self.assertEqual(Product.objects.get(pk=self.sugar[0].pk).parent_group, 'Moved')