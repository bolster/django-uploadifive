from django.conf.urls.defaults import patterns, url
from uploadifive.views import UploadHandler

upload_handler = UploadHandler.as_view()

urlpatterns = patterns('',
    url(r"^$", upload_handler, name="upload"),
    url(r"^(?P<upload_type>[^/]+)/$", upload_handler, name="upload")
)
