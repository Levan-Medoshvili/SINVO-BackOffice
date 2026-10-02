from django.core.management.base import BaseCommand
from django.db import transaction
from commerce.models import Company, Location, Category, Product, StockItem, StockAdjustment, Register


class Command(BaseCommand):
    help = "Create a fictional pilot company/catalog without overwriting existing data or issuing credentials."

    @transaction.atomic
    def handle(self, *args, **options):
        company, _ = Company.objects.get_or_create(code="pilot", defaults={"name": "Pilot Markets"})
        branch, _ = Location.objects.get_or_create(company=company, code="store-1", defaults={"name": "Pilot store", "kind": "branch"})
        Location.objects.get_or_create(company=company, code="warehouse-1", defaults={"name": "Pilot warehouse", "kind": "warehouse"})
        category, _ = Category.objects.get_or_create(company=company, name="Groceries", defaults={"name_ka": "სურსათი"})
        samples = [("DEMO-001", "Milk 1 L", "რძე 1 ლ", 450), ("DEMO-002", "Mineral water", "მინერალური წყალი", 150),
                   ("DEMO-003", "Bread", "პური", 220), ("DEMO-004", "Coffee", "ყავა", 1290)]
        for barcode, name, name_ka, price in samples:
            product, created = Product.objects.get_or_create(company=company, barcode=barcode,
                defaults={"name": name, "name_ka": name_ka, "home_location": branch, "category": category, "price_minor": price})
            if created:
                stock = StockItem.objects.get(product=product, location=branch)
                StockAdjustment.objects.create(stock_item=stock, quantity_milli=100000, reason="Fictional pilot opening stock")
        Register.objects.get_or_create(location=branch, code="pos-1", defaults={"name": "POS 01"})
        self.stdout.write(self.style.SUCCESS("Pilot company, branch, warehouse, catalog and register are ready. Issue the register credential in BackOffice."))
