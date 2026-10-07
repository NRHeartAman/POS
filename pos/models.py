from django.conf import settings
from django.db import models


class Store(models.Model):
    """Receipt header details. Only the first row is used."""
    name    = models.CharField(max_length=150, default='CraveCast Milk Tea')
    address = models.CharField(max_length=255, blank=True)
    tin     = models.CharField('VAT Reg. TIN', max_length=30, blank=True)
    contact = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return self.name

    @classmethod
    def current(cls):
        return cls.objects.first() or cls.objects.create()


class MenuItem(models.Model):
    """A sellable product shown on the register (VAT-inclusive price)."""
    name       = models.CharField(max_length=200, unique=True)
    category   = models.CharField(max_length=50, default='Milk Tea')
    price      = models.DecimalField(max_digits=10, decimal_places=2)
    is_active  = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return self.name


class Ingredient(models.Model):
    """Inventory item deducted when drinks are sold (milk, pearls, powders, cups…)."""
    name            = models.CharField(max_length=150, unique=True)
    unit            = models.CharField(max_length=20, default='g')
    stock_qty       = models.FloatField(default=0)
    low_stock_level = models.FloatField(default=0, help_text='Show a Low Stock warning at or below this amount')
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def is_low(self):
        return self.stock_qty <= self.low_stock_level


class RecipeLine(models.Model):
    """How much of an ingredient one serving of a menu item uses."""
    menu_item       = models.ForeignKey(MenuItem, on_delete=models.CASCADE, related_name='recipe')
    ingredient      = models.ForeignKey(Ingredient, on_delete=models.PROTECT, related_name='used_in')
    qty_per_serving = models.FloatField()

    class Meta:
        unique_together = ('menu_item', 'ingredient')

    def __str__(self):
        return f'{self.menu_item} → {self.qty_per_serving} {self.ingredient.unit} {self.ingredient}'


class PosTransaction(models.Model):
    DISCOUNT_CHOICES = [
        ('',    'None'),
        ('SC',  'Senior Citizen'),
        ('PWD', 'Person with Disability'),
    ]

    receipt_no = models.CharField(max_length=20, unique=True)
    cashier    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='pos_transactions')
    created_at = models.DateTimeField(auto_now_add=True)

    gross_amount     = models.DecimalField(max_digits=12, decimal_places=2)  # VAT-inclusive subtotal
    vatable_sales    = models.DecimalField(max_digits=12, decimal_places=2)
    vat_amount       = models.DecimalField(max_digits=12, decimal_places=2)
    vat_exempt_sales = models.DecimalField(max_digits=12, decimal_places=2)
    less_vat         = models.DecimalField(max_digits=12, decimal_places=2)  # VAT removed on SC/PWD items
    discount_amount  = models.DecimalField(max_digits=12, decimal_places=2)  # 20% SC/PWD discount
    total_due        = models.DecimalField(max_digits=12, decimal_places=2)
    cash_received    = models.DecimalField(max_digits=12, decimal_places=2)
    change_given     = models.DecimalField(max_digits=12, decimal_places=2)

    # SC / PWD cardholder details (required when the discount is given)
    discount_type        = models.CharField(max_length=3, choices=DISCOUNT_CHOICES, blank=True, default='')
    discount_holder_name = models.CharField(max_length=150, blank=True)
    discount_holder_id   = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'OR #{self.receipt_no}'

    @property
    def total_deductions(self):
        return self.less_vat + self.discount_amount


class PosTransactionItem(models.Model):
    transaction    = models.ForeignKey(PosTransaction, on_delete=models.CASCADE, related_name='items')
    menu_item      = models.ForeignKey(MenuItem, on_delete=models.SET_NULL, null=True, blank=True)
    product_name   = models.CharField(max_length=200)
    unit_price     = models.DecimalField(max_digits=10, decimal_places=2)
    quantity       = models.PositiveIntegerField()
    discounted_qty = models.PositiveIntegerField(default=0)  # units consumed by the SC/PWD cardholder
    line_gross     = models.DecimalField(max_digits=12, decimal_places=2)
    line_net       = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f'{self.quantity} × {self.product_name}'


class StockMovement(models.Model):
    """Audit trail of every inventory change."""
    REASONS = [
        ('sale',    'Sale'),
        ('restock', 'Restock'),
        ('adjust',  'Count Adjustment'),
        ('waste',   'Waste / Spoilage'),
    ]
    ingredient  = models.ForeignKey(Ingredient, on_delete=models.CASCADE, related_name='movements')
    change      = models.FloatField()
    stock_after = models.FloatField()
    reason      = models.CharField(max_length=10, choices=REASONS)
    note        = models.CharField(max_length=255, blank=True)
    transaction = models.ForeignKey(PosTransaction, on_delete=models.SET_NULL, null=True, blank=True)
    user        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
