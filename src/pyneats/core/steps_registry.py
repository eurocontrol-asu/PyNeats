from __future__ import annotations

from typing import Any, Callable, Dict, Mapping
from threading import RLock

__all__ = [
    "register",
    "build",
    "known",
    "ensure_kind",
    "RegistryError",
]

class RegistryError(ValueError):
    pass

# Single global registry, but thread-safe.
_REGISTRIES: Dict[str, Dict[str, Callable[..., Any]]] = {
    "interpolator": {},
    "trajectory_parser": {},
    "performance": {},
    "emissions": {},
    "contrails_model": {},
    "non_co2_model": {},
    "climate_impact": {},
}
_LOCK = RLock()

def ensure_kind(kind: str) -> None:
    if kind not in _REGISTRIES:
        raise RegistryError(
            f"Unknown registry kind='{kind}'. "
            f"Known kinds: {', '.join(sorted(_REGISTRIES)) or '(none)'}"
        )

def register(kind: str, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator to register a constructor/class under a kind and a name.

    Usage:
        @register("interpolator", "pycontrails")
        class PyContrailsInterpolator(...): ...
    """
    def deco(ctor: Callable[..., Any]) -> Callable[..., Any]:
        key = name.lower().strip()
        with _LOCK:
            ensure_kind(kind)
            if key in _REGISTRIES[kind]:
                # Allow re-registration to avoid import order pain, but warn loudly.
                # Raise instead if you prefer stricter semantics.
                import warnings
                warnings.warn(
                    f"Overwriting registry entry: {kind}.{key} -> {ctor}",
                    RuntimeWarning,
                    stacklevel=2,
                )
            _REGISTRIES[kind][key] = ctor
        return ctor
    return deco

def build(kind: str, name: str, **params: Any) -> Any:
    key = name.lower().strip()
    with _LOCK:
        ensure_kind(kind)
        try:
            ctor = _REGISTRIES[kind][key]
        except KeyError as e:
            raise RegistryError(
                f"Unknown {kind}='{name}'. Known: {', '.join(sorted(_REGISTRIES[kind])) or '(none)'}"
            ) from e
    return ctor(**params)

def known(kind: str) -> Mapping[str, Callable[..., Any]]:
    with _LOCK:
        ensure_kind(kind)
        # Return a shallow, read-only view
        return dict(_REGISTRIES[kind])
