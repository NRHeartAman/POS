import csv
import json
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (Ingredient, MenuItem, PosTransaction, PosTransactionItem,
                     RecipeLine, StockMovement, Store)
from .services import SC_PWD_RATE, VAT_RATE, CheckoutError, checkout, move_stock


def owner_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_owner:
            messages.error(request, 'Only the owner can open that page.')
            return redirect('pos-register')
        return view(request, *args, **kwargs)
    return wrapper


def _parse_date(value, default):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date() if value else default
    except ValueError:
        return default


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── REGISTER ──────────────────────────────────────────────────────────────────

@login_required
def register_view(request):
    menu = [
        {'id': m.pk, 'name': m.name, 'category': m.category, 'price': float(m.price)}
        for m in MenuItem.objects.filter(is_active=True)
    ]
    return render(request, 'pos/register.html', {
        'menu_json': json.dumps(menu),
        'has_menu':  bool(menu),
        'vat_rate':  float(VAT_RATE),
        'disc_rate': float(SC_PWD_RATE),
    })


@login_required
@require_POST
def checkout_api(request):
    try:
        data = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Invalid request.'}, status=400)

    try:
        txn, no_recipe, low = checkout(
            request.user, data.get('items', []), data.get('cash', 0),
            discount_type=data.get('discount_type', ''),
            holder_name=data.get('holder_name', ''),
            holder_id=data.get('holder_id', ''),
        )
    except (CheckoutError, ValueError, InvalidOperation, KeyError, TypeError) as e:
        return JsonResponse({'ok': False, 'error': str(e) or 'Invalid order.'}, status=400)

    return JsonResponse({
        'ok': True, 'id': txn.pk, 'receipt_no': txn.receipt_no,
        'total_due': float(txn.total_due), 'change': float(txn.change_given),
        'no_recipe': no_recipe, 'low_stock': low,
    })


@login_required
def receipt_view(request, pk):
    txn = get_object_or_404(PosTransaction.objects.select_related('cashier'), pk=pk)
    return render(request, 'pos/receipt.html', {
        'txn': txn, 'items': txn.items.all(), 'store': Store.current(),
    })


# ── TRANSACTIONS / SC-PWD REPORT ──────────────────────────────────────────────

@login_required
def transactions_view(request):
    day  = _parse_date(request.GET.get('date'), timezone.localdate())
    txns = (PosTransaction.objects.filter(created_at__date=day)
            .select_related('cashier').prefetch_related('items'))

    agg = txns.aggregate(
        count=Count('id'), gross=Sum('gross_amount'), net=Sum('total_due'),
        vat=Sum('vat_amount'), vat_exempt=Sum('vat_exempt_sales'), less_vat=Sum('less_vat'),
        sc_disc=Sum('discount_amount', filter=Q(discount_type='SC')),
        sc_count=Count('id', filter=Q(discount_type='SC')),
        pwd_disc=Sum('discount_amount', filter=Q(discount_type='PWD')),
        pwd_count=Count('id', filter=Q(discount_type='PWD')),
    )
    agg = {k: (v if v is not None else Decimal('0')) for k, v in agg.items()}

    top = (PosTransactionItem.objects.filter(transaction__in=txns)
           .values('product_name').annotate(qty=Sum('quantity'), sales=Sum('line_net'))
           .order_by('-qty')[:5])

    return render(request, 'pos/transactions.html', {
        'day': day, 'txns': txns, 'disc_txns': [t for t in txns if t.discount_type],
        'agg': agg, 'top': top,
    })


# ── MENU & RECIPES (Owner) ────────────────────────────────────────────────────

@owner_required
def menu_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action in ('add', 'edit'):
            name     = request.POST.get('name', '').strip()
            category = request.POST.get('category', '').strip() or 'Milk Tea'
            try:
                price = Decimal(request.POST.get('price', ''))
                if price <= 0:
                    raise InvalidOperation
            except InvalidOperation:
                messages.error(request, 'Enter a valid price.')
                return redirect('pos-menu')
            if not name:
                messages.error(request, 'Product name is required.')
                return redirect('pos-menu')

            clash = MenuItem.objects.filter(name__iexact=name)
            if action == 'add':
                if clash.exists():
                    messages.error(request, f'"{name}" is already on the menu.')
                else:
                    item = MenuItem.objects.create(name=name, category=category, price=price)
                    messages.success(request, f'Added "{name}". Now set its recipe so inventory is deducted.')
                    return redirect('pos-recipe', pk=item.pk)
            else:
                item = get_object_or_404(MenuItem, pk=request.POST.get('pk'))
                if clash.exclude(pk=item.pk).exists():
                    messages.error(request, f'"{name}" is already on the menu.')
                else:
                    item.name, item.category, item.price = name, category, price
                    item.save()
                    messages.success(request, f'Updated "{name}".')

        elif action == 'toggle':
            item = get_object_or_404(MenuItem, pk=request.POST.get('pk'))
            item.is_active = not item.is_active
            item.save(update_fields=['is_active', 'updated_at'])
            messages.success(request, f'"{item.name}" is now {"on the register" if item.is_active else "hidden"}.')

        return redirect('pos-menu')

    items = MenuItem.objects.annotate(recipe_count=Count('recipe'))
    categories = sorted({m.category for m in items} | {'Milk Tea', 'Fruit Tea', 'Coffee', 'Add-ons'})
    return render(request, 'pos/menu.html', {'items': items, 'categories': categories})


@owner_required
def recipe_view(request, pk):
    item = get_object_or_404(MenuItem, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add':
            ing = Ingredient.objects.filter(pk=request.POST.get('ingredient')).first()
            qty = _float(request.POST.get('qty'))
            if not ing or not qty or qty <= 0:
                messages.error(request, 'Choose an ingredient and enter an amount above zero.')
            else:
                RecipeLine.objects.update_or_create(menu_item=item, ingredient=ing,
                                                    defaults={'qty_per_serving': qty})
                messages.success(request, f'{ing.name}: {qty:g} {ing.unit} per serving.')
        elif action == 'remove':
            RecipeLine.objects.filter(menu_item=item, pk=request.POST.get('line')).delete()
            messages.success(request, 'Ingredient removed from recipe.')
        return redirect('pos-recipe', pk=item.pk)

    lines = list(item.recipe.select_related('ingredient').order_by('ingredient__name'))
    for l in lines:
        l.servings = int(l.ingredient.stock_qty // l.qty_per_serving) if l.qty_per_serving > 0 else 0
    can_make = min((l.servings for l in lines), default=None)
    return render(request, 'pos/recipe.html', {
        'item': item, 'lines': lines, 'can_make': can_make,
        'ingredients': Ingredient.objects.all(),
    })


# ── INVENTORY (Owner) ─────────────────────────────────────────────────────────

@owner_required
def inventory_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add':
            name  = request.POST.get('name', '').strip()
            unit  = request.POST.get('unit', '').strip() or 'g'
            stock = _float(request.POST.get('stock')) or 0
            low   = _float(request.POST.get('low')) or 0
            if not name:
                messages.error(request, 'Ingredient name is required.')
            elif Ingredient.objects.filter(name__iexact=name).exists():
                messages.error(request, f'"{name}" already exists.')
            else:
                ing = Ingredient.objects.create(name=name, unit=unit, low_stock_level=low)
                if stock:
                    move_stock(ing, stock, 'restock', request.user, 'Opening stock')
                messages.success(request, f'Added {name}.')

        elif action in ('restock', 'waste', 'adjust'):
            ing = get_object_or_404(Ingredient, pk=request.POST.get('pk'))
            qty = _float(request.POST.get('qty'))
            note = request.POST.get('note', '').strip()
            if qty is None or (action != 'adjust' and qty <= 0) or (action == 'adjust' and qty < 0):
                messages.error(request, 'Enter a valid amount.')
            else:
                change = {'restock': qty, 'waste': -qty}.get(action, qty - ing.stock_qty)
                move_stock(ing, change, action, request.user, note)
                messages.success(request, f'{ing.name}: now {ing.stock_qty:g} {ing.unit}.')

        elif action == 'settings':
            ing = get_object_or_404(Ingredient, pk=request.POST.get('pk'))
            low = _float(request.POST.get('low'))
            if low is not None and low >= 0:
                ing.low_stock_level = low
                ing.unit = request.POST.get('unit', ing.unit).strip() or ing.unit
                ing.save()
                messages.success(request, f'Updated {ing.name}.')

        return redirect('pos-inventory')

    ingredients = Ingredient.objects.annotate(used_in_count=Count('used_in'))
    return render(request, 'pos/inventory.html', {
        'ingredients': ingredients,
        'low_count':   sum(1 for i in ingredients if i.is_low),
        'movements':   StockMovement.objects.select_related('ingredient', 'user')[:30],
    })


# ── EXPORT FOR CRAVECAST (Owner) ──────────────────────────────────────────────

@owner_required
def export_view(request):
    today = timezone.localdate()
    start = _parse_date(request.GET.get('start'), today - timedelta(days=6))
    end   = _parse_date(request.GET.get('end'), today)

    rows = (PosTransactionItem.objects
            .filter(transaction__created_at__date__gte=start, transaction__created_at__date__lte=end)
            .annotate(day=TruncDate('transaction__created_at'))
            .values('day', 'product_name')
            .annotate(qty=Sum('quantity'), gross=Sum('line_gross'))
            .order_by('day', 'product_name'))
    rows = [{**r, 'unit_price': f"{r['gross'] / r['qty']:.2f}"} for r in rows]

    if request.GET.get('download'):
        resp = HttpResponse(content_type='text/csv')
        resp['Content-Disposition'] = f'attachment; filename="cravecast_sales_{start}_to_{end}.csv"'
        w = csv.writer(resp)
        # Same columns CraveCast's "Upload Data & Sales" page expects
        w.writerow(['Date', 'Product Name', 'Quantity', 'Unit Price'])
        for r in rows:
            w.writerow([r['day'].isoformat(), r['product_name'], r['qty'], r['unit_price']])
        return resp

    return render(request, 'pos/export.html', {'rows': rows, 'start': start, 'end': end})
