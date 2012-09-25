import json
import logging
import mimetypes
from PIL import Image
from django.http import HttpResponse
from django.utils.decorators import classonlymethod
from django.views.generic import View
from django.views.decorators.csrf import csrf_exempt
from uploadifive.models import Nonce, Upload, NonceException

IMAGE_MIMETYPES = ['image/jpeg', 'image/gif', 'image/png', 'image/jpg']


class JSONResponse(HttpResponse):
    def __init__(self, body, *args, **kwargs):
        body = json.dumps(body)
        super(JSONResponse, self).__init__(body, *args, **kwargs)
        self.mimetype = "application/json"


class UploadHandler(View):
    @classonlymethod
    def as_view(cls, **initkwargs):
        view = super(UploadHandler, cls).as_view(**initkwargs)
        return csrf_exempt(view)

    def process_image_upload(self, data):
        mimetype, encoding = mimetypes.guess_type(data.name)
        if mimetype not in IMAGE_MIMETYPES:
            return None, "Image must be a JPEG, GIF or PNG with the proper extension."
        else:
            try:
                img = Image.open(data)
                img.load()
            except Exception, e:
                #logger.error('Exception while opening image.', exc_info=True)
                print "ERROR %s" % e
            data.seek(0)
        return data, None

    def process_generic_upload(self, data):
        return data, None

    def post(self, request, upload_type=""):
        nonce_key = request.POST.get('nonce', None)

        try:
            nonce = Nonce.objects.lookup(nonce_key)
        except NonceException, e:
            response = JSONResponse({
                'status': 'error',
                'message': e.message
            })
            response.status_code = 400
        else:
            data = request.FILES['Filedata']

            processor = getattr(self, "process_%s_upload" % (upload_type or "generic"))
            data, error = processor(data)

            if error:
                response = JSONResponse({
                    'status': 'error',
                    'message': error
                })
                response.status_code = 400
            else:
                if not nonce.pk:
                    nonce.save()

                upload = Upload(nonce=nonce)
                upload.data = data  # REMINDER: The upload_to processor for Upload.data needs the nonce to be set.
                upload.save()

                response = JSONResponse({
                    'status': 'ok',
                    'url': upload.data.url,
                    'fileID': upload.pk
                })

        return response
