"""Grom AI Studio backend."""

__version__ = "0.2.1"


def _use_system_certificates() -> None:
    """Verify HTTPS against the operating system's certificate store instead of only the bundled Mozilla list, so
    any endpoint whose certificate the machine trusts (a proxy, a self-hosted API) works without extra setup.
    First thing on import: HTTP clients created later pick it up."""
    try:
        import truststore
    except ImportError:  # an environment installed before this dependency existed
        return
    truststore.inject_into_ssl()


_use_system_certificates()
