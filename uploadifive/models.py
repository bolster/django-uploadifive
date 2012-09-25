
import random
from django.conf import settings
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.contrib.auth import get_user_model
from django.db import models

NONCE_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
NONCE_LENGTH = 32

NONCE_MAX_AGE = 60*60

IMAGE_UPLOAD = 'image'
GENERIC_UPLOAD = ''

UPLOAD_TYPES = (
    (IMAGE_UPLOAD, 'Image'),
    (GENERIC_UPLOAD, 'Generic')
)


class NonceException(Exception):
    pass


class NonceManager(models.Manager):
    def random_nonce(self, prefix=""):
        return prefix + "".join([random.choice(NONCE_CHARACTERS) for x in range(NONCE_LENGTH-len(prefix))])

    def provision(self, prefix="", user=None):
        nonce = self.random_nonce(prefix)
        user_id = user.pk if user else ""
        payload = "%s:%s" % (nonce, user_id)
        
        signer = TimestampSigner()
        return signer.sign(payload)

    def lookup(self, signed):
        if signed is None:
            raise NonceException("No nonce was provided.")

        signer = TimestampSigner()
        try:
            payload = signer.unsign(signed, max_age=NONCE_MAX_AGE)
        except BadSignature:
            raise NonceException("The nonce signature was invalid.")
        except SignatureExpired:
            raise NonceException("The nonce has expired.")

        nonce, user_id = payload.split(":")

        User = get_user_model()
        user = User.objects.get(pk=user_id) if user_id else None

        nonce_list = list(Nonce.objects.filter(key=nonce)[:1])

        if nonce_list:
            nonce_obj = nonce_list[0]
            if nonce_obj.user == user:
                return nonce_obj
            else:
                raise NonceException("The current user does not have access to the specified nonce.")
        else:
            return Nonce(key=nonce, user=user)

    def generate_new(self, prefix="", user=None):
        while True:
            candidate = self.random_nonce(prefix)
            if not self.filter(key=candidate).exists():
                return Nonce.objects.create(key=candidate, user=user)

class Nonce(models.Model):
    key = models.CharField(max_length=NONCE_LENGTH, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True)
    created = models.DateTimeField(auto_now_add=True)

    objects = NonceManager()

    def __unicode__(self):
        if self.user:
            return "Nonce for UID#%s: %s" % (self.user_id, self.key)
        else:
            return "Nonce: %s" % self.key

def upload_path_generator(instance, filename):
    processedFilename = "%s_%s" % (instance.nonce.key, filename)
    return processedFilename

class Upload(models.Model):
    nonce = models.ForeignKey(Nonce)
    data = models.FileField(upload_to="uploads/")
    filetype = models.CharField(max_length=16, choices=UPLOAD_TYPES, blank=True, default=GENERIC_UPLOAD)

    def __unicode__(self):
        return self.data.path