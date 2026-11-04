from collections import defaultdict
from pathlib import Path

import cloudinary.uploader
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from tqdm import tqdm

from marketplace.models import Product


IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.jfif', '.png', '.webp', '.gif'}


class Command(BaseCommand):
    help = 'Upload local product images to Cloudinary and update products'

    def add_arguments(self, parser):
        parser.add_argument(
            '--folder',
            default='product_images',
            help='Local folder containing product images (default: product_images)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without uploading images or saving products',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Overwrite images for products that already have an image',
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Process only the first N image files',
        )

    def handle(self, *args, **options):
        output_stream = getattr(self.stdout, '_out', None)
        reconfigure_output = getattr(output_stream, 'reconfigure', None)
        if callable(reconfigure_output):
            reconfigure_output(encoding='utf-8', errors='replace')

        folder = Path(options['folder'])
        dry_run = options['dry_run']
        force = options['force']
        limit = options['limit']

        if limit is not None and limit < 0:
            raise CommandError('--limit must be zero or greater')

        database = settings.DATABASES['default']
        database_host = database.get('HOST') or '(local/default)'
        database_name = database.get('NAME') or '(not configured)'
        folder_label = f"{str(folder).rstrip('/\\')}/"

        self.stdout.write(f'Database host: {database_host}')
        self.stdout.write(f'Database name: {database_name}')
        self.stdout.write(f'Scanning folder: {folder_label}')
        self.stdout.write(f'Dry-run mode: {"ON" if dry_run else "OFF"}')

        if not folder.is_dir():
            self.stdout.write(self.style.ERROR(f'Folder does not exist: {folder}'))
            self._write_summary(
                folder_label=folder_label,
                images_found=0,
                upload_count=0,
                dry_run=dry_run,
                skipped=[],
                orphans=[],
                duplicates=[],
                failed=[],
                products_without_image=None,
            )
            return

        try:
            image_paths = sorted(
                (
                    path for path in folder.iterdir()
                    if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
                ),
                key=lambda path: path.name.casefold(),
            )
        except OSError as error:
            self.stdout.write(self.style.ERROR(f'Could not scan folder {folder}: {error}'))
            self._write_summary(
                folder_label=folder_label,
                images_found=0,
                upload_count=0,
                dry_run=dry_run,
                skipped=[],
                orphans=[],
                duplicates=[],
                failed=[],
                products_without_image=None,
            )
            return

        images_found = len(image_paths)
        if not image_paths:
            self.stdout.write(self.style.WARNING('No supported image files found.'))
            self._write_summary(
                folder_label=folder_label,
                images_found=0,
                upload_count=0,
                dry_run=dry_run,
                skipped=[],
                orphans=[],
                duplicates=[],
                failed=[],
                products_without_image=Product.objects.filter(
                    Q(image__isnull=True) | Q(image='')
                ).count(),
            )
            return

        paths_by_code = defaultdict(list)
        for path in image_paths:
            paths_by_code[path.stem].append(path)

        duplicate_codes = {
            code: paths
            for code, paths in paths_by_code.items()
            if len(paths) > 1
            and len({path.suffix.lower() for path in paths}) > 1
        }
        selected_paths = image_paths if limit is None else image_paths[:limit]
        duplicates = [
            (code, paths)
            for code, paths in sorted(duplicate_codes.items())
        ]
        skipped = []
        orphans = []
        failed = []
        to_upload = []

        for path in selected_paths:
            code = path.stem
            if code in duplicate_codes:
                continue

            try:
                product = Product.objects.get(code=code)
            except Product.DoesNotExist:
                orphans.append(path.name)
                continue

            if product.image and not force:
                skipped.append(path.name)
                continue

            to_upload.append((path, code, product))

        successful_uploads = 0
        if not dry_run and to_upload:
            with tqdm(
                total=len(to_upload),
                desc='Uploading',
                unit='img',
                ncols=100,
                bar_format=(
                    '{l_bar}{bar}| {n_fmt}/{total_fmt} '
                    '[{elapsed}<{remaining}, {rate_fmt}] {postfix}'
                ),
            ) as progress:
                for path, code, product in to_upload:
                    try:
                        result = cloudinary.uploader.upload(
                            str(path),
                            folder=None,
                            public_id=f'ggm-store/products/{code}',
                            overwrite=True,
                            invalidate=True,
                            resource_type='image',
                            use_filename=False,
                            unique_filename=False,
                        )
                        product.image.name = f"image:{result['public_id']}"
                        product.save(update_fields=['image'])
                        successful_uploads += 1
                    except Exception as error:
                        failed.append((path.name, str(error)))
                    progress.set_postfix_str(
                        f'✓ {successful_uploads}  ✗ {len(failed)}'
                    )
                    progress.update(1)

        products_without_image = Product.objects.filter(
            Q(image__isnull=True) | Q(image='')
        ).count()
        self._write_summary(
            folder_label=folder_label,
            images_found=images_found,
            upload_count=len(to_upload) if dry_run else successful_uploads,
            dry_run=dry_run,
            skipped=skipped,
            orphans=orphans,
            duplicates=duplicates,
            failed=failed,
            products_without_image=products_without_image,
        )

    def _write_summary(
        self,
        *,
        folder_label,
        images_found,
        upload_count,
        dry_run,
        skipped,
        orphans,
        duplicates,
        failed,
        products_without_image,
    ):
        upload_label = 'Would upload' if dry_run else 'Uploaded'
        self.stdout.write('============================================')
        self.stdout.write('UPLOAD SUMMARY')
        self.stdout.write('============================================')
        self.stdout.write(f'Scanned folder: {folder_label}')
        self.stdout.write(f'Images found: {images_found}')
        self.stdout.write(
            self.style.SUCCESS(
                f'✓ {upload_label} / Uploaded:     {upload_count}'
            )
        )
        self.stdout.write(self.style.WARNING(
            f'⏭  Skipped (already has image): {len(skipped)}'
        ))
        self.stdout.write(self.style.WARNING(
            f'⚠  Orphans (no matching product): {len(orphans)}'
        ))
        self.stdout.write(self.style.WARNING(
            f'⚠  Duplicate codes: {len(duplicates)}'
        ))
        self.stdout.write(self.style.ERROR(f'✗ Failed: {len(failed)}'))
        products_without_image_label = (
            'Unavailable' if products_without_image is None
            else str(products_without_image)
        )
        self.stdout.write(
            '\nProducts in DB without any image: '
            f'{products_without_image_label}'
        )
        self.stdout.write('============================================')

        self._write_items('Orphans:', (f'- {name}' for name in orphans))
        self._write_items(
            'Duplicate codes:',
            (
                f'- {code} ({", ".join(path.name for path in paths)})'
                for code, paths in duplicates
            ),
        )
        self._write_items(
            'Failed:',
            (f'- {name}: {error}' for name, error in failed),
        )

    def _write_items(self, heading, items):
        self.stdout.write(f'\n{heading}')
        found_items = False
        for item in items:
            found_items = True
            self.stdout.write(f'  {item}')
        if not found_items:
            self.stdout.write('  - None')
