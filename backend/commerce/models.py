import hashlib
import secrets
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models, transaction


class Entity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    class Meta:
        abstract = True


class Company(Entity):
    installation_slot = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    name = models.CharField(max_length=150)
    name_ka = models.CharField(max_length=150, blank=True)
    address = models.CharField(max_length=300, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    theme = models.CharField(max_length=10, choices=[("mint", "Mint"), ("blue", "Blue"), ("neutral", "Neutral")], default="mint")
    code = models.SlugField(unique=True, max_length=50)
    currency = models.CharField(max_length=3, default="GEL", editable=False)
    active = models.BooleanField(default=True)
    advertisement = models.CharField(max_length=250, blank=True, default="Welcome to our store")
    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(installation_slot=1), name="pos_one_company_slot")]
    def __str__(self): return self.name


class Installation(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="pos_one_installation")]


class Location(Entity):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    code = models.SlugField(max_length=50)
    name = models.CharField(max_length=150)
    address = models.CharField(max_length=300, blank=True)
    kind = models.CharField(max_length=12, choices=[("branch", "Branch"), ("warehouse", "Warehouse")])
    active = models.BooleanField(default=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "code"], name="pos_location_company_code")]
    def clean(self):
        if not self._state.adding:
            old = Location.objects.get(pk=self.pk)
            if (old.company_id, old.kind) != (self.company_id, self.kind):
                raise ValidationError("An existing location's company and type cannot change.")
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    def __str__(self): return f"{self.company} / {self.name}"


class Category(Entity):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    name_ka = models.CharField(max_length=100, blank=True)
    def clean(self):
        if not self._state.adding and Category.objects.get(pk=self.pk).company_id != self.company_id:
            raise ValidationError("An existing category cannot move to another company.")
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    def __str__(self): return self.name


class Product(Entity):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    home_location = models.ForeignKey(Location, on_delete=models.PROTECT, help_text="Initial branch or warehouse; additional locations use stock assignments.")
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.PROTECT)
    barcode = models.CharField(max_length=100)
    name = models.CharField(max_length=200)
    name_ka = models.CharField(max_length=200, blank=True)
    unit = models.CharField(max_length=8, choices=[("piece", "Piece"), ("kg", "Kilogram")], default="piece")
    price_minor = models.PositiveBigIntegerField(validators=[MaxValueValidator(100000000)], help_text="Retail price in tetri: 450 = ₾4.50. Includes any configured tax.")
    current_price = models.ForeignKey("PriceRevision", null=True, blank=True, editable=False, on_delete=models.PROTECT, related_name="current_for")
    active = models.BooleanField(default=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "barcode"], name="pos_product_company_barcode")]
    def clean(self):
        if self.home_location_id and self.home_location.company_id != self.company_id:
            raise ValidationError({"home_location": "Location must belong to the product's company."})
        if self.category_id and self.category.company_id != self.company_id:
            raise ValidationError({"category": "Category must belong to the product's company."})
        if self.pk and not self._state.adding:
            old = Product.objects.get(pk=self.pk)
            if (old.company_id, old.unit) != (self.company_id, self.unit):
                raise ValidationError("An existing product's company and unit cannot change; historical and offline sales depend on them.")
    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            if not self._state.adding:
                current = Product.objects.select_for_update().get(pk=self.pk)
                self.current_price = current.current_price
            super().save(*args, **kwargs)
            if not self.current_price_id or self.current_price.price_minor != self.price_minor:
                revision = PriceRevision.objects.create(product=self, price_minor=self.price_minor)
                Product.objects.filter(pk=self.pk).update(current_price=revision)
                self.current_price = revision
            StockItem.objects.get_or_create(product=self, location=self.home_location)
    def __str__(self): return self.name


class PriceRevision(Entity):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="prices")
    price_minor = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Published prices are immutable; change the product's retail price.")
        super().save(*args, **kwargs)


class StockItem(Entity):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_items")
    location = models.ForeignKey(Location, on_delete=models.PROTECT)
    quantity_milli = models.BigIntegerField(default=0, editable=False)
    enabled = models.BooleanField(default=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["product", "location"], name="pos_stock_product_location")]
    def clean(self):
        if self.product_id and self.location_id and self.product.company_id != self.location.company_id:
            raise ValidationError("Product and location must belong to the same company.")
        if not self._state.adding:
            old = StockItem.objects.get(pk=self.pk)
            if (old.product_id, old.location_id) != (self.product_id, self.location_id):
                raise ValidationError("A stock assignment's product and location cannot change.")
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    def __str__(self): return f"{self.product} / {self.location}"


class Register(Entity):
    location = models.ForeignKey(Location, on_delete=models.PROTECT)
    code = models.SlugField(max_length=50)
    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)
    token_hash = models.CharField(max_length=64, blank=True, editable=False)
    last_seen = models.DateTimeField(null=True, blank=True, editable=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["location", "code"], name="pos_register_location_code")]
    def clean(self):
        if self.location_id and self.location.kind != "branch":
            raise ValidationError({"location": "A register must belong to a branch."})
        if not self._state.adding and Register.objects.get(pk=self.pk).location_id != self.location_id:
            raise ValidationError("An existing register cannot move to another branch; create a new register.")
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    def issue_token(self):
        secret = secrets.token_urlsafe(32)
        self.token_hash = hashlib.sha256(secret.encode()).hexdigest()
        self.save(update_fields=["token_hash"])
        return f"{self.id}.{secret}"
    def __str__(self): return f"{self.location} / {self.name}"


class Sale(Entity):
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    cashier_session = models.ForeignKey("CashierSession", null=True, blank=True, on_delete=models.PROTECT)
    register = models.ForeignKey(Register, on_delete=models.PROTECT)
    client_id = models.UUIDField()
    payload_hash = models.CharField(max_length=64)
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)
    total_minor = models.PositiveBigIntegerField()
    cash_received_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default="GEL")
    class Meta:
        constraints = [models.UniqueConstraint(fields=["register", "client_id"], name="pos_sale_register_client")]


class SaleLine(Entity):
    sale = models.ForeignKey(Sale, related_name="lines", on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    price_revision = models.ForeignKey(PriceRevision, on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    barcode = models.CharField(max_length=100)
    quantity_milli = models.PositiveBigIntegerField()
    unit_price_minor = models.PositiveBigIntegerField()
    total_minor = models.PositiveBigIntegerField()


class StockMovement(Entity):
    stock_item = models.ForeignKey(StockItem, on_delete=models.PROTECT)
    quantity_milli = models.BigIntegerField()
    reason = models.CharField(max_length=30)
    note = models.CharField(max_length=250, blank=True)
    sale_line = models.OneToOneField(SaleLine, null=True, blank=True, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class StockAdjustment(Entity):
    stock_item = models.ForeignKey(StockItem, on_delete=models.PROTECT)
    quantity_milli = models.BigIntegerField(help_text="Signed change in thousandths: +1000 adds one piece/kg, -1000 removes one.")
    reason = models.CharField(max_length=250)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, editable=False, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Posted adjustments are immutable; post a compensating adjustment.")
        self.full_clean()
        if not self.quantity_milli or abs(self.quantity_milli) > 1000000000:
            raise ValidationError("Enter a nonzero adjustment within the supported quantity range.")
        with transaction.atomic():
            stock = StockItem.objects.select_for_update().get(pk=self.stock_item_id)
            super().save(*args, **kwargs)
            StockItem.objects.filter(pk=stock.pk).update(quantity_milli=models.F("quantity_milli") + self.quantity_milli)
            StockMovement.objects.create(stock_item=stock, quantity_milli=self.quantity_milli,
                reason="adjustment", note=self.reason, actor=self.actor)


class AccessPermission(models.Model):
    code = models.SlugField(primary_key=True, max_length=50)
    name = models.CharField(max_length=100)
    def __str__(self): return self.name


class AccessGroup(Entity):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    permissions = models.ManyToManyField(AccessPermission, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "name"], name="pos_group_company_name")]
        verbose_name = "Access group"
    def clean(self):
        if not self._state.adding and AccessGroup.objects.get(pk=self.pk).company_id != self.company_id:
            raise ValidationError("An existing group cannot move to another company.")
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    def __str__(self): return f"{self.company} / {self.name}"


class EmployeeAccess(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, primary_key=True, on_delete=models.CASCADE, related_name="pos_access")
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    application = models.CharField(max_length=10, choices=[("backend", "Backend"), ("cashier", "Cashier"), ("both", "Both")], default="cashier")
    all_branches = models.BooleanField(default=False)
    branches = models.ManyToManyField(Location, blank=True, limit_choices_to={"kind": "branch"})
    groups = models.ManyToManyField(AccessGroup, blank=True, related_name="members")
    permissions = models.ManyToManyField(AccessPermission, blank=True, help_text="Added to permissions inherited from access groups.")
    def clean(self):
        if not self._state.adding and EmployeeAccess.objects.filter(pk=self.pk).exclude(company_id=self.company_id).exists():
            raise ValidationError("Create a separate employee account when changing company; retain historical access records.")
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        if not self.user.is_superuser:
            type(self.user).objects.filter(pk=self.user_id).update(is_staff=self.application in {"backend", "both"})
    def __str__(self): return str(self.user)


class DeviceEnrollment(models.Model):
    installation_id = models.UUIDField(primary_key=True)
    register = models.OneToOneField(Register, on_delete=models.PROTECT)
    secret_hash = models.CharField(max_length=64)
    address_hint = models.CharField(max_length=300, blank=True)
    enrolled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class EnrollmentRequest(models.Model):
    installation_id = models.UUIDField(primary_key=True)
    secret_hash = models.CharField(max_length=64)
    branch_name = models.CharField(max_length=150)
    branch_address = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")], default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)


class PairingCode(Entity):
    code_hash = models.CharField(max_length=64, unique=True)
    branch = models.ForeignKey(Location, on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    installation_id = models.UUIDField(null=True, blank=True)


class CashierSession(Entity):
    register = models.ForeignKey(Register, on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)


class LoginRateBucket(models.Model):
    key = models.CharField(primary_key=True, max_length=64)
    attempts = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField()


class LiveBasket(models.Model):
    register = models.OneToOneField(Register, primary_key=True, on_delete=models.PROTECT)
    basket_id = models.UUIDField()
    revision = models.PositiveBigIntegerField(default=0)
    state = models.CharField(max_length=12, default="empty")
    lines_json = models.TextField(default="[]")
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    seen_at = models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name = "Live checkout"
        verbose_name_plural = "Live checkouts"
    def __str__(self): return str(self.register)


class BasketCommand(Entity):
    register = models.ForeignKey(Register, on_delete=models.PROTECT)
    basket_id = models.UUIDField()
    expected_revision = models.PositiveBigIntegerField()
    line_key = models.CharField(max_length=80)
    product_name = models.CharField(max_length=200)
    reason = models.CharField(max_length=250)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    status = models.CharField(max_length=12, choices=[("pending", "Pending"), ("applied", "Confirmed by POS"), ("rejected", "Rejected by POS"), ("expired", "Expired")], default="pending")
    result_detail = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
