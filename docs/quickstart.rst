==========
Quickstart
==========

Installation
============

Pre-requisites
--------------

* Python 3.11 or higher
* Setuptools 77.0.0 or higher
* Django 5.2 or newer
* Only the PostgreSQL database is supported

Install from PyPI
-----------------

Install from PyPI with pip:

.. code-block:: bash

    pip install vng-api-common

Configure the Django settings
-----------------------------

1. Add ``vng_api_common`` to ``INSTALLED_APPS``, with the rest of the dependencies:

    .. code-block:: python

        INSTALLED_APPS = [
            ...,
            'django_filters',
            'vng_api_common',
            'vng_api_common.authorizations',
            'vng_api_common.notifications',  # optional
            'vng_api_common.audittrails',  # optional
            'drf_spectacular',
            'rest_framework',
            'rest_framework_gis',
            'solo',  # required for authorizations and notifications
            ...
        ]

2. Add the required middleware:

    .. code-block:: python
       :linenos:
       :emphasize-lines: 7,10

        MIDDLEWARE = [
            'django.middleware.security.SecurityMiddleware',
            'django.contrib.sessions.middleware.SessionMiddleware',
            'django.middleware.common.CommonMiddleware',
            'django.middleware.csrf.CsrfViewMiddleware',
            'django.contrib.auth.middleware.AuthenticationMiddleware',
            'vng_api_common.authorizations.middleware.AuthMiddleware',
            'django.contrib.messages.middleware.MessageMiddleware',
            'django.middleware.clickjacking.XFrameOptionsMiddleware',
            'vng_api_common.middleware.APIVersionHeaderMiddleware',
        ]

3. Add the default API settings:

    .. code-block:: python

        from vng_api_common.conf.api import *  # noqa

        ...

    Imports are white-listed in the shipped settings module, so it's actually
    safe to do ``import *`` ;)

4. See ``vng_api_common/conf/api.py`` for a list of available settings.


5. The ``SITE_DOMAIN`` setting must be explicitly defined in your ``settings`` or set using an environment variable,
    as it is used to defines the main domain of the site.


Usage
=====

Run-time functionality
----------------------

See the rest of the documentation for the available modules and packages.

.. _ZRC: https://github.com/VNG-Realisatie/zaken-api
.. _DRC: https://github.com/VNG-Realisatie/documenten-api
.. _ZTC: https://github.com/VNG-Realisatie/catalogi-api
.. _BRC: https://github.com/VNG-Realisatie/besluiten-api
