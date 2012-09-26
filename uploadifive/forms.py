import logging
import os
import types
from django import forms
from uploadifive.models import Nonce, Upload, NonceException


def get_or_none(model, **kwargs):
    try:
        return model.objects.get(**kwargs)
    except model.DoesNotExist:
        return None


def wrap_function(name, suffix, wrapped, inner):
    def inner_clean(self):
        if wrapped:
            value = wrapped()
        else:
            s = super(type(self), self)
            s_fn = getattr(s, "clean_%s_%s" % (name, suffix), None)
            if s_fn:
                value = s_fn()
            else:
                value = self.cleaned_data["%s_%s" % (name, suffix)]
        return inner(self, value)
    return inner_clean


def create_clean_nonce(name, suffix, wrapped):
    def inner_clean(self, value):
        try:
            setattr(self, "%s_nonce_instance" % name,
                Nonce.objects.lookup(value))
        except NonceException, e:
            raise forms.ValidationError(e.message)
        return value

    return wrap_function(name, "nonce", wrapped, inner_clean)


def create_clean_ref(name, suffix, wrapped):
    def inner_clean(self, value):
        nonce_instance = getattr(self, "%s_nonce_instance" % name, None)
        if nonce_instance:
            upload = list(nonce_instance.upload_set.filter(pk=value)[:1])
            upload = upload[0] if upload else None
            setattr(self, "%s_upload" % name, upload)
        return value

    return wrap_function(name, suffix, wrapped, inner_clean)


def add_function(self, name, suffix, generator):
    method_name = "clean_%s_%s" % (name, suffix)
    wrapped = getattr(self, method_name, None)
    fn = generator(name, suffix, wrapped)
    method = types.MethodType(fn, self, type(self))
    setattr(self, method_name, method)


class NoncedMixin(object):
    NONCED_FIELDS = []

    def __init__(self, *args, **kwargs):
        initial = kwargs.setdefault('initial', {})
        instance = self.instance

        nonce_initial = {}
        for name in self.NONCED_FIELDS:
            nonce_name = "%s_nonce" % name
            nonce_initial[nonce_name] = Nonce.objects.provision(user=instance)

            add_function(self, name, "nonce", create_clean_nonce)
            add_function(self, name, "ref", create_clean_ref)

        initial.update(nonce_initial)

        super(NoncedMixin, self).__init__(*args, **kwargs)


class RetainedUploadFieldsForm(object):
    AUTO_PREFIX = "auto_"
    UPLOAD_PREFIX = "upload_"
    SAVED_PREFIX = "saved_"
    _nonce = None
    EXTRA_UPLOAD_FIELDS = {}

    def __init__(self, *args, **kwargs):
        super(RetainedUploadFieldsForm, self).__init__(*args, **kwargs)

        if 'data' in kwargs:
            """
            We dynamically create fields for uploaded files.
            """

            uploads = [self.id_from_name(x) for x in kwargs['data'] if x.startswith(self.UPLOAD_PREFIX)]

            nonce_key = kwargs['data'].get('nonce', None)
            nonce = get_or_none(Nonce, key=nonce_key) if nonce_key is not None else None

            if nonce is not None:
                referenced_uploads = dict((str(x.pk), x) for x in Upload.objects.filter(nonce=nonce))
                for upload in uploads:
                    try:
                        obj = referenced_uploads[upload]
                        self.add_fields(prefix=self.UPLOAD_PREFIX,
                            name=str(obj.pk), label=obj.data.url)
                    except Exception, e:
                        logger.error('Referenced field not found.', exc_info=True)
                        print "Referenced field not found: %s" % e

        if self.instance:
            referenced_files = dict((str(x.pk), x) for x in self.get_saveable_objects())

            if 'data' in kwargs:
                # After the initial round, rely solely on data passed from the client
                files = [self.id_from_name(x, self.SAVED_PREFIX)
                    for x in kwargs['data'] if x.startswith(self.SAVED_PREFIX)]
            else:
                files = [str(x.pk) for x in referenced_files.values()]

            for file_id in files:
                try:
                    obj = referenced_files[file_id]
                    self.add_fields(prefix=self.SAVED_PREFIX,
                        name=file_id, label=obj.get_absolute_url(),
                        extra_kwargs={
                            'description': {
                                'initial': getattr(obj, 'description', None)
                            }
                        })
                except Exception, e:
                    logger.error('Exception while professing file ID.', exc_info=True)
                    print "Difficulty processing file ID %s" % file_id

    def add_fields(self, prefix, name, label, extra_kwargs={}):
        self.fields[prefix + name] = forms.CharField(initial=name,
            label=label, max_length=250, widget=forms.HiddenInput)

        for extra_name, (field_type, field_kwargs) in self.EXTRA_UPLOAD_FIELDS.items():
            field_kwargs = dict(field_kwargs)
            field_kwargs.update(extra_kwargs.get(extra_name, {}))
            self.fields[self.get_extra_field_name(prefix, name, extra_name)] = \
                field_type(**field_kwargs)

    def get_saveable_objects(self):
        return []

    def id_from_name(self, field, prefix=UPLOAD_PREFIX):
        return field[len(prefix):]

    @property
    def nonce(self):
        if not self._nonce:
            nonce_key = self.cleaned_data['nonce']
            self._nonce = Nonce.objects.get(key=nonce_key)
        return self._nonce

    def get_extra_field_name(self, prefix, name, extra_name):
        return "%s%s%s_%s" % (self.AUTO_PREFIX, prefix, name, extra_name)

    def get_extra_data(self, prefix, name):
        extras = {}

        for extra_name in self.EXTRA_UPLOAD_FIELDS:
            full_name = self.get_extra_field_name(prefix, name, extra_name)
            extras[extra_name] = self.cleaned_data.get(full_name, None)

        return extras

    def get_saved(self):
        prefix = self.SAVED_PREFIX

        referenced_files = dict((str(x.pk), x) for x in self.get_saveable_objects())

        if self.data:
            # After the initial round, rely solely on data passed from the client
            files = [self.id_from_name(x, prefix)
                for x in self.data if x.startswith(prefix)]
        else:
            files = [str(x.pk) for x in referenced_files.values()]

        for file_id in files:
            try:
                extras = self.get_extra_data(prefix, file_id)
                yield referenced_files[file_id], extras
            except Exception, e:
                logger.error('Exception while getting saved file info.', exc_info=True)
                print "Could not get saved info for %s: %s" % (file_id, e)

    def get_uploads(self, target_prefix):
        prefix = self.UPLOAD_PREFIX

        upload_fields = [field for field in self.fields if
            field.startswith(prefix)]

        for field in upload_fields:
            upload_id = self.id_from_name(field)
            upload = Upload.objects.get(id=upload_id, nonce=self.nonce)

            _base, ext = os.path.splitext(upload.data.name)
            upload_name = "%s-%s%s" % (target_prefix, upload_id, ext)

            extras = self.get_extra_data(prefix, upload_id)

            yield field, upload_name, upload.data, extras
