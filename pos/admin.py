from django.contrib import admin
from .models import (Ingredient, MenuItem, PosTransaction, PosTransactionItem,
                     RecipeLine, StockMovement, Store)


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ('name', 'address', 'tin', 'contact')


class RecipeLineInline(admin.TabularInline):
    model = RecipeLine
    extra = 1


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display  = ('name', 'category', 'price', 'is_active')
    list_filter   = ('category', 'is_active')
    list_editable = ('price', 'is_active')
    search_fields = ('name',)
    inlines       = [RecipeLineInline]


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display  = ('name', 'stock_qty', 'unit', 'low_stock_level')
    search_fields = ('name',)


class PosTransactionItemInline(admin.TabularInline):
    model = PosTransactionItem
    extra = 0
    can_delete = False
    readonly_fields = ('product_name', 'unit_price', 'quantity', 'discounted_qty', 'line_gross', 'line_net')
    exclude = ('menu_item',)


@admin.register(PosTransaction)
class PosTransactionAdmin(admin.ModelAdmin):
    list_display    = ('receipt_no', 'created_at', 'cashier', 'total_due', 'discount_type', 'discount_holder_name')
    list_filter     = ('discount_type', 'created_at')
    search_fields   = ('receipt_no', 'discount_holder_name', 'discount_holder_id')
    inlines         = [PosTransactionItemInline]
    readonly_fields = [f.name for f in PosTransaction._meta.fields]


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'ingredient', 'change', 'stock_after', 'reason', 'user', 'note')
    list_filter  = ('reason', 'ingredient')
