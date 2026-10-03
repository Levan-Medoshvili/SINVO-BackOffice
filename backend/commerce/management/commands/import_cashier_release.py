"""Register a CI-published signed bundle without creating a branch rollout."""
import json
import re
from contextlib import ExitStack
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from commerce.updates import import_release


class Command(BaseCommand):
    help = "Verify a signed Cashier bundle and make it available in BackOffice."

    def add_arguments(self, parser):
        parser.add_argument("directory", help="Directory containing manifest.json, manifest.sig and the package")
        parser.add_argument("--actor", required=True, help="Existing active BackOffice superuser username for the audit record")

    def handle(self, *args, **options):
        user_model = get_user_model()
        actor = user_model.objects.filter(**{user_model.USERNAME_FIELD: options["actor"]}, is_active=True, is_superuser=True).first()
        if not actor:
            raise CommandError("--actor must name an existing active BackOffice superuser.")
        root = Path(options["directory"]).resolve()

        def local_file(name):
            candidate = root / name
            if candidate.is_symlink() or not candidate.is_file() or candidate.resolve().parent != root:
                raise CommandError("The release bundle must contain regular files directly inside its directory.")
            return candidate

        try:
            manifest = local_file("manifest.json")
            if manifest.stat().st_size > 65536:
                raise CommandError("Release manifest exceeds its size limit.")
            metadata = json.loads(manifest.read_bytes())
            filename = metadata.get("filename") if isinstance(metadata, dict) else None
            if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}", filename):
                raise CommandError("Invalid package filename in release manifest.")
            paths = [manifest, local_file("manifest.sig"), local_file(filename)]
            with ExitStack() as stack:
                files = [File(stack.enter_context(p.open("rb")), name=p.name) for p in paths]
                release = import_release(*files, actor, allow_existing=True)
        except ValidationError as error:
            raise CommandError("; ".join(error.messages)) from error
        except (OSError, ValueError) as error:
            raise CommandError(f"Could not read the release bundle: {error}") from error
        self.stdout.write(self.style.SUCCESS(
            f"Verified and available in BackOffice: {release.version} ({release.platform}). Choose target branches under Cashier updates."
        ))
