from django.db import migrations

def add_permission(apps, schema_editor):
    apps.get_model('commerce','AccessPermission').objects.get_or_create(code='manage_integrations',
        defaults={'name':'Configure company integrations'})

class Migration(migrations.Migration):
    dependencies=[('commerce','0007_catalog_integrations_hardware')]
    operations=[migrations.RunPython(add_permission,migrations.RunPython.noop)]
