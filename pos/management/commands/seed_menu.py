from django.core.management.base import BaseCommand
from django.db import transaction

from pos.models import Ingredient, MenuItem, RecipeLine, Store
from pos.services import move_stock

# name: (unit, opening stock, low-stock level)
INGREDIENTS = {
    'Black Tea Base':    ('mL', 8000, 1000),
    'Milk':              ('mL', 15000, 2000),
    'Sugar':             ('g', 3000, 500),
    'Brown Sugar Syrup': ('mL', 2000, 300),
    'Tapioca Pearls':    ('g', 4000, 600),
    'Taro Powder':       ('g', 2500, 300),
    'Okinawa Syrup':     ('mL', 1500, 200),
    'Wintermelon Syrup': ('mL', 1500, 200),
    'Coffee Beans':      ('g', 1000, 150),
    'Cups (16oz)':       ('pcs', 300, 50),
}

# product: (category, price, {ingredient: qty per serving})
MENU = {
    'Classic Milk Tea':     ('Milk Tea', 95,  {'Black Tea Base': 150, 'Milk': 80, 'Sugar': 20, 'Tapioca Pearls': 60, 'Cups (16oz)': 1}),
    'Okinawa Milk Tea':     ('Milk Tea', 115, {'Black Tea Base': 150, 'Milk': 100, 'Okinawa Syrup': 30, 'Tapioca Pearls': 60, 'Cups (16oz)': 1}),
    'Taro Milk Tea':        ('Milk Tea', 120, {'Milk': 150, 'Taro Powder': 25, 'Sugar': 15, 'Tapioca Pearls': 60, 'Cups (16oz)': 1}),
    'Wintermelon Milk Tea': ('Milk Tea', 105, {'Black Tea Base': 150, 'Milk': 80, 'Wintermelon Syrup': 30, 'Tapioca Pearls': 60, 'Cups (16oz)': 1}),
    'Brown Sugar Milk':     ('Milk Tea', 125, {'Milk': 200, 'Brown Sugar Syrup': 30, 'Tapioca Pearls': 70, 'Cups (16oz)': 1}),
    'Spanish latte':        ('Coffee',   110, {'Coffee Beans': 18, 'Milk': 180, 'Sugar': 20, 'Cups (16oz)': 1}),
    'Extra Pearls':         ('Add-ons',  15,  {'Tapioca Pearls': 50}),
}


class Command(BaseCommand):
    help = 'Load a sample milk tea menu, ingredients and recipes (skips anything that already exists).'

    @transaction.atomic
    def handle(self, *args, **options):
        Store.current()
        ing_objs, new_ing, new_items = {}, 0, 0
        for name, (unit, stock, low) in INGREDIENTS.items():
            ing, created = Ingredient.objects.get_or_create(name=name, defaults={'unit': unit, 'low_stock_level': low})
            if created:
                move_stock(ing, stock, 'restock', note='Opening stock (sample data)')
                new_ing += 1
            ing_objs[name] = ing

        for name, (cat, price, recipe) in MENU.items():
            item, created = MenuItem.objects.get_or_create(name=name, defaults={'category': cat, 'price': price})
            if created:
                new_items += 1
                for ing_name, qty in recipe.items():
                    RecipeLine.objects.create(menu_item=item, ingredient=ing_objs[ing_name], qty_per_serving=qty)

        self.stdout.write(self.style.SUCCESS(f'Added {new_ing} ingredient(s) and {new_items} menu item(s).'))
