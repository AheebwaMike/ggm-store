import marketplace.storage
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0017_product_created_at_productgroup_home_order_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='productgroup',
            name='image',
            field=models.ImageField(
                blank=True,
                null=True,
                storage=marketplace.storage.CloudinaryMediaStorage(),
                upload_to='product_groups/',
            ),
        ),
    ]
