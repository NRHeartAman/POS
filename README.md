# CraveCast POS

A point-of-sale system for milk tea shops, with Senior Citizen / PWD discounts, recipe-based inventory, and printable receipts.

This project is **separate from the CraveCast forecasting system** (`CAPSTONEM`). It has its own database (`cravecast_pos.sqlite3`) and never touches CraveCast's PostgreSQL database. Sales move to CraveCast through a CSV export.

## Start the POS

Double-click **`START_POS.bat`**. It sets itself up on first run, then opens http://127.0.0.1:8001/ in your browser.
Keep the black window open while selling, and close it to stop the POS.

Manual start:

```
.venv\Scripts\activate
python manage.py migrate
python manage.py runserver 127.0.0.1:8001
```

## Accounts

| Role    | Can do |
|---------|--------|
| Owner   | Everything: register, transactions, menu & recipes, inventory, CSV export, users |
| Cashier | Register and transactions only |

Add cashiers in **Users & Store** (Django admin): click **Users**, then **Add user**, and set the role to *Cashier*.
Set the shop name, address and VAT TIN printed on receipts in **Users & Store → Stores**.

## Senior Citizen / PWD discount (RA 9994 / RA 10754)

Menu prices include 12% VAT. For each item the cardholder consumes:

1. VAT is removed: `price ÷ 1.12`
2. 20% is deducted from that amount

Example: a ₱120 Taro Milk Tea becomes ₱107.14 without VAT. The 20% discount is ₱21.43, so the customer pays **₱85.71**.

In group orders, only the cardholder's items are discounted. Set how many units of each item are theirs with the green **SC/PWD** counter.
The POS won't complete a discounted sale without the cardholder's name and ID number. The details are printed on the receipt and listed in the SC/PWD log on the **Transactions** page.

## Inventory

- Every product can have a **recipe**, the amount of each ingredient per serving (**Menu & Recipes → Set recipe**).
- Each sale deducts the recipe ingredients. **Inventory** shows the stock levels, low-stock warnings, and a log of every movement.
- Use **Restock** for deliveries, **Waste** for spoiled stock, and **Count** to set the stock to what you physically counted.

## Sending sales to CraveCast

1. POS → **Export to CraveCast**: pick the dates, then click **Download CSV**.
2. CraveCast → log in as Owner → **Upload Data & Sales**: upload the file.

The CSV uses CraveCast's columns: `Date, Product Name, Quantity, Unit Price`, with one row per product per day.
Keep product names the same in both systems so the forecasts match.

## Sample data

`python manage.py seed_menu` loads a sample milk tea menu with ingredients and recipes. It skips anything that already exists.

## Backups

All POS data is in the single file `cravecast_pos.sqlite3`. To back up, stop the POS and copy that file.

## Tests

```
.venv\Scripts\python.exe manage.py test pos
```

`prototype/index.html` is the first single-file version of the POS, kept for reference.
