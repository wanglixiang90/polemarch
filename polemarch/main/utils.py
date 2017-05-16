# pylint: disable=invalid-name
from __future__ import unicode_literals

import sys
import tempfile
import time
import traceback
import os
from os.path import dirname

import six
from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator as BasePaginator
from django.template import loader
from django.utils import translation

from . import exceptions as ex


def import_class(path):
    m_len = path.rfind(".")
    class_name = path[m_len + 1:len(path)]
    module = __import__(path[0:m_len], globals(), locals(), [class_name])
    return getattr(module, class_name)


def project_path():
    if hasattr(sys, "frozen"):
        return dirname(dirname(sys.executable))
    return dirname(dirname(__file__))


def get_render(name, data, trans='en'):
    translation.activate(trans)
    config = loader.get_template(name)
    result = config.render(data).replace('\r', '')
    translation.deactivate()
    return result


class tmp_file(object):
    def __init__(self, mode="w", bufsize=0, **kwargs):
        kw = not six.PY3 and {"bufsize": bufsize} or {}
        kwargs.update(kw)
        fd = tempfile.NamedTemporaryFile(mode, **kwargs)
        self.fd = fd

    def write(self, wr_string):
        result = self.fd.write(wr_string)
        self.fd.flush()
        return result

    def __getattr__(self, name):
        return getattr(self.fd, name)

    def __del__(self):
        self.fd.close()

    def __enter__(self):
        return self

    def __exit__(self, type_e, value, tb):
        self.fd.close()
        if value is not None:
            return False


class tmp_file_context(object):
    def __init__(self, *args, **kwargs):
        self.tmp = tmp_file(*args, **kwargs)

    def __enter__(self):
        return self.tmp

    def __exit__(self, type_e, value, tb):
        self.tmp.close()
        if os.path.exists(self.tmp.name):
            os.remove(self.tmp.name)


class Lock(object):

    TIMEOUT = 60*60*24
    GLOBAL = "global-deploy"
    SCHEDULER = "celery-beat"

    class AcquireLockException(Exception):
        pass

    def __init__(self, id, payload=None, repeat=1, err_msg=""):
        self.id, start = None, time.time()
        while time.time() - start <= repeat:
            if cache.add(id, payload, self.TIMEOUT):
                self.id = id
                return
            time.sleep(0.01)
        raise self.AcquireLockException(err_msg)

    def __enter__(self):
        return self

    def __exit__(self, type_e, value, tb):
        self.release()

    def release(self):
        cache.delete(self.id)

    def __del__(self):
        self.release()


class __LockAbstractDecorator(object):
    _err = "Wait until the end."
    _lock_key = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.kwargs["err_msg"] = self.kwargs.get("err_msg", self._err)

    def execute(self, func, *args, **kwargs):
        if self._lock_key is not None:
            with Lock(self._lock_key, **self.kwargs):
                return func(*args, **kwargs)
        return func(*args, **kwargs)

    def __call__(self, original_function):
        def wrapper(*args, **kwargs):
            return self.execute(original_function, *args, **kwargs)
        return wrapper


class service_lock(__LockAbstractDecorator):
    _err = "Service locked. Wait until the end."

    def execute(self, func, *args, **kwargs):
        self._lock_key = kwargs.get('pk', None)
        return super(service_lock, self).execute(func, *args, **kwargs)


class ModelHandlers(object):
    def __init__(self, tp):
        self.type = tp

    def list(self):
        return getattr(settings, self.type, {})

    def backend(self, name):
        try:
            backend = self.list()[name].get('BACKEND', None)
            if backend is None:
                raise ex.PMException("Backend is 'None'.")
            return import_class(backend)
        except KeyError or ImportError:
            raise ex.UnknownModelHandlerException(name)

    def opts(self, name):
        return self.list().get(name, {}).get('OPTIONS', {})

    def get_object(self, name, obj):
        return self.backend(name)(obj, **self.opts(name))


class assertRaises(object):
    def __init__(self, *args, **kwargs):
        self._verbose = kwargs.pop("verbose", False)
        self._excepts = tuple(args)

    def __enter__(self):
        return self  # pragma: no cover

    def __exit__(self, exc_type, exc_val, exc_tb):
        return exc_type is not None and not issubclass(exc_type, self._excepts)


# noinspection PyUnreachableCode
class raise_context(assertRaises):

    def execute(self, func, *args, **kwargs):
        with self.__class__(self._excepts, verbose=self._verbose):
            return func(*args, **kwargs)
        return sys.exc_info()

    def __enter__(self):
        return self.execute

    def __call__(self, original_function):
        def wrapper(*args, **kwargs):
            return self.execute(original_function, *args, **kwargs)

        return wrapper


class exception_with_traceback(raise_context):
    def __init__(self, *args, **kwargs):
        super(exception_with_traceback, self).__init__(**kwargs)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val is not None:
            exc_val.traceback = traceback.format_exc()
            six.reraise(exc_type, exc_val, exc_tb)


class _RedirectionOutput(object):
    _streams = []

    def __init__(self, new_stream=six.StringIO()):
        self.stream = new_stream
        self._old_streams = {}

    def __enter__(self):
        for stream in self._streams:
            self._old_streams[stream] = getattr(sys, stream)
            setattr(sys, stream, self.stream)
        return self.stream

    def __exit__(self, exctype, excinst, exctb):
        for stream in self._streams:
            setattr(sys, stream, self._old_streams.pop(stream))


class redirect_stdout(_RedirectionOutput):
    _streams = ["stdout"]


class redirect_stderr(_RedirectionOutput):
    _streams = ["stderr"]


class redirect_stdin(_RedirectionOutput):
    _streams = ["stdin"]


class redirect_stdany(_RedirectionOutput):
    _streams = ["stdout", "stderr"]


class Paginator(BasePaginator):
    def __init__(self, qs, chunk_size=getattr(settings, "PAGE_LIMIT")):
        super(Paginator, self).__init__(qs, chunk_size)

    def __iter__(self):
        for page in range(1, self.num_pages + 1):
            yield self.page(page)

    def items(self):
        for page in self:
            for obj in page.object_list:
                obj.paginator = self
                obj.page = page
                yield obj


class task(object):
    def __init__(self, app, *args, **kwargs):
        self.app = app
        self.args, self.kwargs = args, kwargs

    def __call__(self, task_cls):

        self.kwargs["name"] = "{c.__module__}.{c.__name__}".format(c=task_cls)

        @self.app.task(*self.args, **self.kwargs)
        def wrapper(*args, **kwargs):
            return task_cls(*args, **kwargs).start()

        return wrapper


class BaseTask(object):
    def __init__(self, app, *args, **kwargs):
        super(BaseTask, self).__init__()
        self.app = app
        self.args, self.kwargs = args, kwargs
        self.task_class = self.__class__

    def start(self):
        return self.run()

    def run(self):  # pragma: no cover
        # pylint: disable=notimplemented-raised,
        raise NotImplemented
