import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from pywebpush import WebPushException, webpush

from marketplace.models import PushSubscription


class Command(BaseCommand):
    help = 'Sends a test push notification to all subscribed devices'

    def handle(self, *args, **kwargs):
        if not settings.VAPID_PRIVATE_KEY:
            raise CommandError('VAPID_PRIVATE_KEY is not configured.')
        if not settings.VAPID_ADMIN_EMAIL:
            raise CommandError('VAPID_ADMIN_EMAIL is not configured.')

        subscriptions = PushSubscription.objects.all()
        if not subscriptions.exists():
            self.stdout.write(self.style.WARNING('No subscriptions found.'))
            return

        payload = json.dumps({
            'title': 'GGM Store Test',
            'body': 'This is a test notification from your Django backend!',
            'url': '/my-orders/',
        })
        success = 0
        failed = 0

        for subscription in subscriptions:
            try:
                webpush(
                    subscription_info={
                        'endpoint': subscription.endpoint,
                        'keys': {
                            'p256dh': subscription.p256dh,
                            'auth': subscription.auth,
                        },
                    },
                    data=payload,
                    vapid_private_key=settings.VAPID_PRIVATE_KEY,
                    vapid_claims={
                        'sub': f'mailto:{settings.VAPID_ADMIN_EMAIL}',
                    },
                    ttl=3600,
                    timeout=10,
                )
                success += 1
            except WebPushException as exc:
                failed += 1
                if (
                    exc.response is not None
                    and exc.response.status_code in {404, 410}
                ):
                    subscription.delete()
                    self.stdout.write(
                        self.style.WARNING(
                            f'Removed expired subscription #{subscription.pk}.'
                        )
                    )
                else:
                    self.stderr.write(
                        f'Push delivery failed for subscription #{subscription.pk}.'
                    )

        summary = f'Sent: {success}, Failed: {failed}'
        if failed:
            self.stdout.write(summary)
        else:
            self.stdout.write(self.style.SUCCESS(summary))
        if failed:
            raise CommandError('One or more push notifications failed.')
