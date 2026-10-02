from django.db import migrations


def seed(apps, schema_editor):
    Permission = apps.get_model("commerce", "AccessPermission")
    for code, name in [("remove_basket_line", "Cashier: reduce quantities and remove basket items"), ("supervise_basket", "BackOffice: view live baskets and request item removal")]:
        Permission.objects.get_or_create(code=code, defaults={"name": name})


class Migration(migrations.Migration):
    dependencies = [("commerce", "0002_accesspermission_loginratebucket_sale_cashier_and_more")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
