from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('commerce', '0008_integration_permission')]
    operations = [
        migrations.AddField(model_name='company', name='identification_number', field=models.CharField(max_length=32, blank=True)),
        migrations.AddField(model_name='company', name='email', field=models.EmailField(max_length=254, blank=True)),
    ]
