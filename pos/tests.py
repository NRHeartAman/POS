import json
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from .models import Ingredient, MenuItem, PosTransaction, RecipeLine, StockMovement


class PosTests(TestCase):
    def setUp(self):
        self.cashier = User.objects.create_user('cashier', password='pw12345!', role='CASHIER')
        self.owner   = User.objects.create_user('boss', password='pw12345!', role='OWNER')
        self.taro = MenuItem.objects.create(name='Taro Milk Tea', price=Decimal('120.00'))
        self.oki  = MenuItem.objects.create(name='Okinawa Milk Tea', price=Decimal('115.00'))
        self.milk = Ingredient.objects.create(name='Milk', unit='mL', stock_qty=1000, low_stock_level=300)
        RecipeLine.objects.create(menu_item=self.taro, ingredient=self.milk, qty_per_serving=200)
        self.client.force_login(self.cashier)

    def post(self, payload):
        return self.client.post(reverse('pos-checkout'), json.dumps(payload), content_type='application/json')

    def test_senior_discount_math_and_inventory(self):
        # 2 Taro (1 for the senior) + 1 Okinawa
        data = self.post({
            'items': [
                {'menu_item_id': self.taro.pk, 'quantity': 2, 'discounted_qty': 1},
                {'menu_item_id': self.oki.pk,  'quantity': 1, 'discounted_qty': 0},
            ],
            'cash': 500, 'discount_type': 'SC', 'holder_name': 'Lola Nena', 'holder_id': 'SC-123',
        }).json()
        self.assertTrue(data['ok'], data)

        t = PosTransaction.objects.get(pk=data['id'])
        # Senior's taro: 120 / 1.12 = 107.14 ; 20% = 21.43 ; pays 85.71
        self.assertEqual(t.gross_amount,     Decimal('355.00'))
        self.assertEqual(t.vat_exempt_sales, Decimal('107.14'))
        self.assertEqual(t.less_vat,         Decimal('12.86'))
        self.assertEqual(t.discount_amount,  Decimal('21.43'))
        self.assertEqual(t.total_due,        Decimal('320.71'))   # 235 + 85.71
        self.assertEqual(t.vatable_sales,    Decimal('209.82'))   # 235 / 1.12
        self.assertEqual(t.vat_amount,       Decimal('25.18'))
        self.assertEqual(t.change_given,     Decimal('179.29'))
        self.assertEqual(t.receipt_no, f'{t.pk:08d}')

        # Inventory: 2 × 200 mL deducted and logged; Okinawa has no recipe
        self.milk.refresh_from_db()
        self.assertEqual(self.milk.stock_qty, 600)
        self.assertEqual(StockMovement.objects.get(reason='sale').change, -400)
        self.assertEqual(data['no_recipe'], ['Okinawa Milk Tea'])

        # Next sale drops milk to 200 mL → low stock warning
        data = self.post({'items': [{'menu_item_id': self.taro.pk, 'quantity': 2, 'discounted_qty': 0}], 'cash': 240}).json()
        self.assertEqual(data['low_stock'][0]['item'], 'Milk')

        # Pages render
        self.assertContains(self.client.get(reverse('pos-receipt', args=[t.pk])), 'Lola Nena')
        self.assertContains(self.client.get(reverse('pos-transactions')), 'SC-123')
        self.assertContains(self.client.get(reverse('pos-register')), 'Taro Milk Tea')

    def test_validation_blocks_bad_orders(self):
        item = [{'menu_item_id': self.taro.pk, 'quantity': 1, 'discounted_qty': 1}]
        self.assertIn('ID', self.post({'items': item, 'cash': 500, 'discount_type': 'PWD'}).json()['error'])
        self.assertIn('Insufficient', self.post({'items': item, 'cash': 10, 'discount_type': 'PWD',
                                                 'holder_name': 'A', 'holder_id': '1'}).json()['error'])
        bad = [{'menu_item_id': self.taro.pk, 'quantity': 1, 'discounted_qty': 2}]
        self.assertFalse(self.post({'items': bad, 'cash': 500}).json()['ok'])
        self.assertEqual(PosTransaction.objects.count(), 0)
        self.milk.refresh_from_db()
        self.assertEqual(self.milk.stock_qty, 1000)

    def test_owner_pages_and_export(self):
        for name in ('pos-menu', 'pos-inventory', 'pos-export'):
            self.assertRedirects(self.client.get(reverse(name)), reverse('pos-register'), fetch_redirect_response=False)

        self.post({'items': [{'menu_item_id': self.taro.pk, 'quantity': 3, 'discounted_qty': 1}],
                   'cash': 500, 'discount_type': 'PWD', 'holder_name': 'Juan', 'holder_id': 'PWD-9'})
        self.client.force_login(self.owner)
        for name in ('pos-menu', 'pos-inventory', 'pos-export'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertContains(self.client.get(reverse('pos-recipe', args=[self.taro.pk])), '2 cups')  # (1000 − 600 sold) / 200

        csv_text = self.client.get(reverse('pos-export') + '?download=1').content.decode()
        lines = csv_text.strip().splitlines()
        self.assertEqual(lines[0], 'Date,Product Name,Quantity,Unit Price')
        self.assertTrue(lines[1].endswith(',Taro Milk Tea,3,120.00'), lines[1])

        # Restock + count adjustment
        self.client.post(reverse('pos-inventory'), {'action': 'restock', 'pk': self.milk.pk, 'qty': '500'})
        self.milk.refresh_from_db()
        self.assertEqual(self.milk.stock_qty, 900)   # 1000 − 600 + 500
        self.client.post(reverse('pos-inventory'), {'action': 'adjust', 'pk': self.milk.pk, 'qty': '850'})
        self.milk.refresh_from_db()
        self.assertEqual(self.milk.stock_qty, 850)

    def test_seed_menu(self):
        call_command('seed_menu', verbosity=0)
        self.assertTrue(MenuItem.objects.filter(name='Wintermelon Milk Tea').exists())
        self.assertEqual(MenuItem.objects.get(name='Wintermelon Milk Tea').recipe.count(), 5)
        call_command('seed_menu', verbosity=0)   # safe to run twice
        self.assertEqual(Ingredient.objects.filter(name='Milk').count(), 1)
