==============
Change history
==============

2.7.0 (2025-07-10)
------------------

**New features**

* Add ``__and__`` operator for ``Scope`` class

**Maintenance**

* Add support for Django 5.2
* [#105] Remove ``coreapi`` dependency

2.6.7 (2025-06-30)
------------------

**Bugfixes**

* [#103] Fix 500 error that occurred with ``iat`` in future, log a warning
* Add JWT expiry validation based on ``iat``

**Maintenance**

* Upgrade PyJWT to 2.10.1

2.6.6 (2025-06-04)
------------------

* [open-zaak/open-zaak#635] Rename JWT_LEEWAY setting to TIME_LEEWAY and add it to UntilNowValidator

2.6.5 (2025-05-27)
------------------

**Bugfixes/QOL**

* No longer rely on zgw-consumers for generate_jwt util
* [#90] Make requests_mock dependency optional (can be installed with ``pip install commonground-api-common[oas]``)

**Maintenance**

* [maykinmedia/open-api-framework#140] Upgrade python to 3.12
* [maykinmedia/open-api-framework#132] Replace check_sphinx.py with make
* [maykinmedia/open-api-framework#133] Replace black, isort and flake8 with ruff and update code-quality workflow

2.6.4 (2025-05-16)
------------------

* [maykinmedia/open-klant#414] Move ``vng_api_common.filters.Backend`` -> ``vng_api_common.filters_backend.Backend``
* [maykinmedia/open-klant#414] Fix help texts not showing in generated OAS for ``vng_api_common.filters_backend.Backend``

2.6.3 (2025-05-12)
------------------

* Fix BSNField validator to mention BSN instead of RSIN in validation error message
* Migrate from ``iso639`` to ``iso639-lang``
* [maykinmedia/open-klant#249] Add default to the help_text of the ``pageSize`` attribute

2.6.2 (2025-04-16)
------------------

* [maykinmedia/open-klant#341] Fix ``help_text`` field in FilterSet

2.6.1 (2025-04-14)
------------------

* [open-zaak/open-zaak#1799] Fix ``DurationField`` to consistently support negative durations.

2.6.0 (2025-04-07)
------------------

**New features**

* [open-zaak/open-zaak#1970] Add several DRF hyperlinked field classes that cache the results of ``reverse()`` to
  avoid running the same logic multiple times. This can improve performance for serialization
  with hyperlinked fields by quite a bit, especially for list operations

    * ``vng_api_common.serializers.CachedHyperlinkedIdentityField``
    * ``vng_api_common.serializers.CachedHyperlinkedRelatedField``
    * ``vng_api_common.serializers.CachedNestedHyperlinkedRelatedField``

2.5.5 (2025-03-21)
------------------

* [maykinmedia/open-api-framework#59] Remove ``SITE_DOMAIN`` default value and update docs

2.5.4 (2025-03-20)
------------------

* [maykinmedia/open-api-framework#59] Remove ``django.contrib.sites`` dependency and add ``SITE_DOMAIN`` environment variable

2.5.3 (2025-03-18)
------------------

* Add Dutch translations for rest_framework pagination parameters

2.5.2 (2025-03-06)
------------------

* Add English translation for ``HyperlinkedIdentityField`` description

2.5.1 (2025-02-10)
------------------

* Add English translations for Applicatie model

2.5.0 (2025-02-06)
------------------

* Update setup-config docs to use example directive and add extra example values to models

2.4.1 (2025-01-14)
------------------

* Make geojson fields optional by catching ImproperlyConfigured errors

2.4.0 (2025-01-13)
------------------

* [#57] Improved validation of RSIN and BSN by creating a generic validator.

2.3.0 (2025-01-09)
------------------

* Add ConfigurationStep for Applicatie model
* [#29] Replaced drf-yasg with drf-spectacular
* [#29] Removed management commands to generate markdown files for scopes and notifications channels:
    * ``generate_autorisaties``
    * ``generate_notificaties``


2.2.0 (2024-12-10)
------------------

* Add support for ``django-setup-configuration``, add a ``ConfigurationStep`` for ``JWTSecret``

2.1.2 (2024-11-29)
------------------

* Version 2.1.1 tagged the incorrect commit (`403494178746fba882208ee7e49f9dd6a2c6c5f6`)

2.1.1 (2024-11-29)
------------------

* Move zgw-consumers-oas import to related function

2.1.0 (2024-11-29)
------------------

* Update `notifications-api-common` to version `0.3.1`
* [#44] include missing `Service` migration from `zgw-consumers`
* Add `check_autorisaties_subscription` keyword argument to `_test_nrc_config`
  which allows checking for subscriptions to be optional (defaults to `True`) for the
  authorization service.
* Modify `_test_nrc_config` check to skip extra checks if Notificaties API is not configured
* Add `raise_exceptions` option to `get_client` util
* Remove assertion in `to_internal_data` util to avoid errors in case of empty (204) responses

2.0.1 (2024-11-22)
------------------

* move zgw-consumers-oas to ``testutils`` instead of ``tests``, to avoid pulling in irrelevant test deps in other projects

2.0.0 (2024-11-22)
------------------

* upgrade to zgw-consumers 0.35.1
* remove zds-client dependency and replace with ``ape_pie.APIClient``
* upgrade to notifications-api-common>=0.3.0
* replace ``get_auth_headers`` with ``generate_jwt`` util

.. warning::

    If your project uses OAS test utilities, make sure to install them via ``commonground-api-common[testutils]``

.. warning::

    The ``APICredential`` class has been removed in favor of the ``Service`` model from zgw-consumers,
    a data migration is added to create ``Service`` instances from ``APICredential`` instances

.. warning::

    Several notifications related models (``NotificationsConfig`` and ``Subscription``) as well as
    the constants ``SCOPE_NOTIFICATIES_CONSUMEREN_LABEL`` and ``SCOPE_NOTIFICATIES_PUBLICEREN_LABEL`` have
    been removed, since they are defined in ``notifications-api-common`` and were a not deleted yet in ``commonground-api-common``

1.13.4 (2024-10-25)
-------------------

* Move AuthMiddleware to authorizations app, to avoid unnecessary migrations for projects that don't use ``vng_api_common.authorizations``

1.13.3 (2024-09-05)
-------------------

* Dropped support for Python 3.8 and Python 3.9
* [#33] Added dynamic pagination


1.13.2 (2024-07-05)
-------------------

* Added *identificatie* to ``UniekeIdentificatieValidator`` error message


1.13.1 (2024-05-28)
-------------------

* Marked notifications view scopes as private
* Added natural keys to authorization models


1.13.0 (2024-03-01)
-------------------

* Added support of Django 4.2
* Removed support of Python 3.7
* Added support of Python 3.11
