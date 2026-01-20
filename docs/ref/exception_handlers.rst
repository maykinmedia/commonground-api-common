=========================
Exception handlers
=========================

The library provides a shared DRF exception handler that converts errors into
the DSO-compliant ``application/problem+json`` format.

Projects can register custom exception handlers using the exception handler
registry.

.. automodule:: vng_api_common.exception_handling
    :members: register_exception_handler
