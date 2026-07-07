import warnings

from rest_framework.routers import (
    APIRootView as _APIRootView,
    DefaultRouter as DRFDefaultRouter,
)
from rest_framework_nested import routers


class APIRootView(_APIRootView):
    permission_classes = ()


class NestedRegisteringMixin(DRFDefaultRouter):
    _nested_routers: list

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("trailing_slash", False)
        super().__init__(*args, **kwargs)
        self._nested_routers = []

    def get_urls(self):
        urls = super().get_urls()
        for nested_router in self._nested_routers:
            urls += nested_router.urls
        return urls

    def register(self, prefix, viewset, nested=None, *args, **kwargs):
        super().register(prefix, viewset, *args, **kwargs)

        if not nested:
            return

        if "base_name" in kwargs:
            warnings.warn(
                "base_name kwarg is deprecated, use basename instead",
                DeprecationWarning,
            )
            kwargs["basename"] = kwargs["base_name"]
            del kwargs["base_name"]

        base_name = kwargs.get("basename") or self.get_default_basename(viewset)

        nested_router = NestedSimpleRouter(
            self, prefix, lookup=base_name, trailing_slash=False
        )
        for _nested in nested:
            nested_router.register(
                _nested.prefix, _nested.viewset, _nested.nested, **_nested.kwargs
            )

        self._nested_routers.append(nested_router)


class NestedSimpleRouter(NestedRegisteringMixin, routers.NestedSimpleRouter):
    pass


class DefaultRouter(NestedRegisteringMixin, DRFDefaultRouter):
    APIRootView: type[_APIRootView] = APIRootView


class Nested:
    def __init__(self, prefix, viewset, nested=None, **kwargs):
        self.prefix = prefix
        self.viewset = viewset
        self.nested = nested
        self.kwargs = kwargs

    def __repr__(self):
        return "Nested(prefix={!r}, viewset={!r}".format(self.prefix, self.viewset)
