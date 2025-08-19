=========================================
Generating UML diagrams for Django models
=========================================

This library provides a Sphinx directive to display UML diagrams as images for a component's
models. This can be used to show the relationships between different models for components
that expose APIs.

To make use of this directive, it should be added to ``extensions`` in ``docs/conf.py``:

.. code::

    extensions = [
        ...
        "vng_api_common.diagrams.uml_images",
        ...
    ]

The directive can then be used in reStructuredText files:

.. code::

    .. uml_images::
        :apps: app1 app2 app3
        :grouped_apps:
            app2:
            - app2
            - app3
        :excluded_models: ModelName1 ModelName2

* ``apps``: the apps with models for which UML images should be generated
* ``excluded_models``: optional, specific models that should be excluded from image generation
* ``grouped_apps``: optional, allows grouping multiple apps under one section
