from django.urls import path
from . import views

urlpatterns = [
    path('',                        views.register_view,     name='pos-register'),
    path('checkout/',               views.checkout_api,      name='pos-checkout'),
    path('receipt/<int:pk>/',       views.receipt_view,      name='pos-receipt'),
    path('transactions/',           views.transactions_view, name='pos-transactions'),
    path('menu/',                   views.menu_view,         name='pos-menu'),
    path('menu/<int:pk>/recipe/',   views.recipe_view,       name='pos-recipe'),
    path('inventory/',              views.inventory_view,    name='pos-inventory'),
    path('export/',                 views.export_view,       name='pos-export'),
]
