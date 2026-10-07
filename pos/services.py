# pos/services.py
# ─────────────────────────────────────────────────────────────────────────────
# Checkout and inventory logic.
#
# Philippine Senior Citizen / PWD rules (RA 9994 / RA 10754):
#   Menu prices are VAT-inclusive (12%). For every unit consumed by the
#   cardholder, VAT is removed first (price / 1.12), then 20% is deducted
#   from that VAT-exempt amount. Other units in the same order are charged
#   normally.

from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from .models import (Ingredient, MenuItem, PosTransaction, PosTransactionItem,
                     RecipeLine, StockMovement)

VAT_RATE    = Decimal('0.12')
SC_PWD_RATE = Decimal('0.20')
CENT        = Decimal('0.01')


class CheckoutError(Exception):
    pass


def money(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def compute_totals(lines):
    """lines: dicts with unit_price (Decimal), quantity, discounted_qty."""
    regular_gross  = Decimal('0')
    discount_gross = Decimal('0')
    for l in lines:
        regular_gross  += l['unit_price'] * (l['quantity'] - l['discounted_qty'])
        discount_gross += l['unit_price'] * l['discounted_qty']

    vatable    = regular_gross / (1 + VAT_RATE)
    vat        = regular_gross - vatable
    vat_exempt = discount_gross / (1 + VAT_RATE)
    less_vat   = discount_gross - vat_exempt
    discount   = vat_exempt * SC_PWD_RATE
    total      = regular_gross + vat_exempt - discount

    return {
        'gross_amount':     money(regular_gross + discount_gross),
        'vatable_sales':    money(vatable),
        'vat_amount':       money(vat),
        'vat_exempt_sales': money(vat_exempt),
        'less_vat':         money(less_vat),
        'discount_amount':  money(discount),
        'total_due':        money(total),
    }


def line_net(unit_price, quantity, discounted_qty):
    regular = unit_price * (quantity - discounted_qty)
    disc    = unit_price * discounted_qty / (1 + VAT_RATE) * (1 - SC_PWD_RATE)
    return money(regular + disc)


def move_stock(ingredient, change, reason, user=None, note='', txn=None):
    """Apply a stock change and record it. Stock never goes below zero."""
    ingredient.stock_qty = max(0.0, round(ingredient.stock_qty + change, 3))
    ingredient.save(update_fields=['stock_qty', 'updated_at'])
    StockMovement.objects.create(
        ingredient=ingredient, change=change, stock_after=ingredient.stock_qty,
        reason=reason, note=note, transaction=txn,
        user=user if user and user.is_authenticated else None,
    )


def _deduct_inventory(lines, txn, user):
    """Deduct recipe ingredients for the sold items. Returns (no_recipe, low_stock)."""
    usage, no_recipe = {}, []
    recipes = (RecipeLine.objects.filter(menu_item__in=[l['menu_item'] for l in lines])
               .select_related('ingredient'))
    by_item = {}
    for r in recipes:
        by_item.setdefault(r.menu_item_id, []).append(r)

    for l in lines:
        rlines = by_item.get(l['menu_item'].pk)
        if not rlines:
            no_recipe.append(l['product_name'])
            continue
        for r in rlines:
            usage[r.ingredient_id] = usage.get(r.ingredient_id, 0) + r.qty_per_serving * l['quantity']

    low = []
    for ing in Ingredient.objects.select_for_update().filter(pk__in=usage):
        move_stock(ing, -usage[ing.pk], 'sale', user, f'OR #{txn.receipt_no}', txn)
        if ing.is_low:
            low.append({'item': ing.name, 'remaining': round(ing.stock_qty, 2), 'unit': ing.unit})
    return no_recipe, low


@transaction.atomic
def checkout(user, cart, cash, discount_type='', holder_name='', holder_id=''):
    """
    cart: [{'menu_item_id': int, 'quantity': int, 'discounted_qty': int}, ...]
    Prices are always taken from the database, never from the browser.
    Returns (PosTransaction, no_recipe_names, low_stock_list).
    """
    if not cart:
        raise CheckoutError('The order is empty.')

    ids  = [int(c['menu_item_id']) for c in cart]
    menu = {m.pk: m for m in MenuItem.objects.filter(pk__in=ids, is_active=True)}

    merged = {}
    for c in cart:
        item = menu.get(int(c['menu_item_id']))
        if not item:
            raise CheckoutError('One of the items is no longer on the menu. Refresh the page.')
        qty  = int(c.get('quantity', 0))
        dqty = int(c.get('discounted_qty', 0))
        if qty <= 0 or dqty < 0 or dqty > qty:
            raise CheckoutError(f'Invalid quantity for {item.name}.')
        line = merged.setdefault(item.pk, {
            'menu_item': item, 'product_name': item.name, 'unit_price': item.price,
            'quantity': 0, 'discounted_qty': 0,
        })
        line['quantity']       += qty
        line['discounted_qty'] += dqty
    lines = list(merged.values())

    has_discount  = any(l['discounted_qty'] for l in lines)
    discount_type = (discount_type or '').upper()
    holder_name   = (holder_name or '').strip()
    holder_id     = (holder_id or '').strip()
    if has_discount:
        if discount_type not in ('SC', 'PWD'):
            raise CheckoutError('Choose Senior Citizen or PWD for the discount.')
        if not holder_name or not holder_id:
            raise CheckoutError("Enter the cardholder's name and ID number.")
    else:
        discount_type, holder_name, holder_id = '', '', ''

    totals = compute_totals(lines)
    cash   = money(Decimal(str(cash or 0)))
    if cash < totals['total_due']:
        raise CheckoutError(f"Insufficient cash. Total due is ₱{totals['total_due']:,.2f}.")

    txn = PosTransaction.objects.create(
        receipt_no='TMP-' + timezone.now().strftime('%H%M%S%f'),
        cashier=user if user and user.is_authenticated else None,
        cash_received=cash,
        change_given=cash - totals['total_due'],
        discount_type=discount_type,
        discount_holder_name=holder_name,
        discount_holder_id=holder_id,
        **totals,
    )
    txn.receipt_no = f'{txn.pk:08d}'
    txn.save(update_fields=['receipt_no'])

    PosTransactionItem.objects.bulk_create([
        PosTransactionItem(
            transaction=txn, menu_item=l['menu_item'], product_name=l['product_name'],
            unit_price=l['unit_price'], quantity=l['quantity'], discounted_qty=l['discounted_qty'],
            line_gross=money(l['unit_price'] * l['quantity']),
            line_net=line_net(l['unit_price'], l['quantity'], l['discounted_qty']),
        )
        for l in lines
    ])

    no_recipe, low = _deduct_inventory(lines, txn, user)
    return txn, no_recipe, low
