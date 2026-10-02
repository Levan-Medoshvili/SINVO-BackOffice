"""Create the first administrator without resetting any existing account."""
import os
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = 'Create the first administrator using server-private environment values.'

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write('An administrator already exists; its password was preserved.')
            return
        username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', '')
        if len(password) < 20:
            raise CommandError('Provide the server-generated initial administrator password.')
        if User.objects.filter(username=username).exists():
            raise CommandError('This username already exists. Choose a different administrator username.')
        User.objects.create_superuser(username=username, password=password, name='SimplePOS', surname='Administrator')
        self.stdout.write('Initial administrator created. Credentials remain in the root-owned server file.')
