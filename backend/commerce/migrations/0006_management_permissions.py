from django.db import migrations

def permissions(apps, schema_editor):
    Permission=apps.get_model('commerce','AccessPermission')
    for code,name in [('manage_advertisements','Manage advertisements across company branches'),('manage_updates','Publish Cashier updates across company branches')]:
        Permission.objects.get_or_create(code=code,defaults={'name':name})

class Migration(migrations.Migration):
    dependencies=[('commerce','0005_branch_management')]
    operations=[migrations.RunPython(permissions,migrations.RunPython.noop)]
