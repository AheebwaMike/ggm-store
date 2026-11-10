from .dev import *

STORAGES = {
    'default': STORAGES['default'],
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
