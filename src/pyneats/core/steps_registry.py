""" NEATS Steps Registry Module

This module provides a registry system for NEATS processing steps. It implements
a factory pattern that allows dynamic registration and instantiation of processing components
based on their interface types. 
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, TypeVar, cast
from threading import RLock
import warnings

__all__ = [
    # public API
    "register",
    "build",
    "known",
    "RegistryError",
]


class RegistryError(ValueError):
    """Exception raised for errors in the NEATS registry operations."""
    pass


# Constructor type for a given T (class or factory function)
T = TypeVar("T")
Ctor = Callable[..., T]


# ---- Single, type-keyed registry --------------------------------------------


class _BigRegistry:
    """
    Single registry keyed by *interface type* then by entry name.

    Internals:
      _items: Dict[type[Any], Dict[str, Callable[..., Any]]]
    We keep it Any-typed inside and cast at the edges to preserve strong
    generics on the public API
    """

    def __init__(self) -> None:
        self._items: Dict[type[Any], Dict[str, Callable[..., Any]]] = {}
        self._lock = RLock()

    def register(self, t: type[T], name: str) -> Callable[[Ctor[T]], Ctor[T]]:
        """Register a constructor or class under an interface type and name.
    
        This method implements a decorator pattern for registering implementations.
        Names are case-insensitive and whitespace is stripped. Thread-safety is 
        ensured
        """
        key = name.lower().strip()

        def deco(ctor: Ctor[T]) -> Ctor[T]:
            with self._lock:
                bucket = self._items.setdefault(t, {})
                if key in bucket:
                    warnings.warn(
                        f"Overwriting registry entry for {t.__name__!s}.{key} -> {ctor}",
                        RuntimeWarning,
                        stacklevel=2,
                    )
                # Store as Callable[..., Any] internally
                bucket[key] = cast(Callable[..., Any], ctor)
            return ctor

        return deco

    def build(self, t: type[T], name: str, **params: Any) -> T:
        """Build an instance of a registered implementation.
    
        This method instantiates a registered constructor/class with the given parameters.
        Names are case-insensitive and whitespace is stripped. 
        """
        key = name.lower().strip()

        with self._lock:
            try:
                ctor_any = self._items[t][key]
            except KeyError as e:
                known = ", ".join(sorted(self._items.get(t, {}))) or "(none)"
                raise RegistryError(
                    f"Unknown {t.__name__} name='{name}'. Known: {known}"
                ) from e

        ctor = cast(Ctor[T], ctor_any)
        return ctor(**params)

    def known(self, t: type[T]) -> Mapping[str, Ctor[T]]:
        """ Return a shallow copy, cast back to the precise ctor type """
        with self._lock:
            bucket = self._items.get(t, {})
            return {k: cast(Ctor[T], v) for k, v in bucket.items()}


# global singleton
_REGISTRY = _BigRegistry()


# ---- Public API (thin wrappers around the singleton) -------------------------


def register(t: type[T], name: str) -> Callable[[Ctor[T]], Ctor[T]]:
    """
    Decorator to register a constructor/class under an *interface type* and a name.

    """
    return _REGISTRY.register(t, name)


def build(t: type[T], name: str, **params: Any) -> T:
    """
    Build an instance registered under interface type `t` with the given `name`.
    Strongly typed: returns `T` inferred from `t`.
    """
    return _REGISTRY.build(t, name, **params)


def known(t: type[T]) -> Mapping[str, Ctor[T]]:
    """Return a read-only mapping of registered names -> constructors for interface `t`."""
    return _REGISTRY.known(t)
