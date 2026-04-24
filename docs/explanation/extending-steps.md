# Extending Steps

PyNeats pipelines are assembled from **named implementations of `Protocol`
interfaces**, resolved at runtime through a step registry. This page explains
how the registry works and how to plug in a custom step without touching
runner code.

## The registry pattern

Each pipeline stage defines a `Protocol` in its `protocol.py` module (e.g.
`TrajectoryParser`, `TrajectoryInterpolator`, `PerformanceModel`,
`EmissionModel`, `NonCO2Model`, `ClimateImpactModel`,
`WeatherProviderProtocol`). Concrete classes register against one of these
protocols with a short name:

```python
from pyneats.core.steps_registry import register
from pyneats.steps.parsing.protocol import TrajectoryParser

@register(TrajectoryParser, "neats")
class NeatsTrajectoryParser:
    def __call__(self, source): ...
```

Runners don't import concrete classes. They look them up by name via `build`:

```python
from pyneats.core.steps_registry import build
from pyneats.steps.parsing.protocol import TrajectoryParser

parser = build(TrajectoryParser, "neats", model_type="CTFM")
flight = parser(source_df)
```

`build(protocol, name, **params)` instantiates the registered class with
`**params`. Names are **case-insensitive** and whitespace-stripped. Unknown
names raise `RegistryError` with the list of available entries.

## Registered protocols

| Protocol                     | Module                                          | Built-in names         |
|------------------------------|-------------------------------------------------|------------------------|
| `TrajectoryParser`           | `pyneats.steps.parsing.protocol`                | `neats`, `adsb`        |
| `TrajectoryInterpolator`     | `pyneats.steps.interpolation.protocol`          | see `known(...)`       |
| `PerformanceModel`           | `pyneats.steps.performance.protocol`            | BADA 3/4 variants      |
| `EmissionModel`              | `pyneats.steps.emissions.protocol`              | DLR, PyContrails, …    |
| `ContrailsModel`             | `pyneats.steps.climate_functions.protocol`      | CoCiP variants         |
| `NonCO2Model`                | `pyneats.steps.climate_functions.protocol`      | aCCFs, `open_airclim`  |
| `ClimateImpactModel`         | `pyneats.steps.climate_metrics.protocol`        | GWP / EAGWP variants   |
| `WeatherProviderProtocol`    | `pyneats.steps.weather.protocol`                | DWD ICON, ERA5         |

List the entries available at runtime:

```python
from pyneats.core.steps_registry import known
from pyneats.steps.emissions.protocol import EmissionModel

print(list(known(EmissionModel)))
```

## Adding a custom step

Two requirements: structurally satisfy the target `Protocol`, and register
under a unique name. The example below adds a custom emission model.

```python
from pyneats.core.steps_registry import register
from pyneats.steps.emissions.protocol import EmissionModel
from pyneats.steps.emissions.views import FlightWithEmissions
from pyneats.steps.performance.views import FlightWithPerformance

@register(EmissionModel, "my_custom_ei")
class MyCustomEmissionModel:
    def __init__(self, scaling: float = 1.0) -> None:
        self.scaling = scaling

    def __call__(self, flight: FlightWithPerformance) -> FlightWithEmissions:
        # compute nox_ei, nvpm_ei, h2o_ei, co2_ei, so2_ei on flight.data
        ...
        return FlightWithEmissions(flight.data)
```

Once the module defining the class is imported (typically by your
application's entry point or via a plugin entry-point), select it by name
through `RunnerConfig`:

```python
from pyneats.runners.flight import RunnerConfig
from pyneats.runners.large_emitter import FlightRunnerLargeEmitter

cfg = RunnerConfig(
    emissions="my_custom_ei",
    params={"emissions": {"scaling": 1.2}},
)
runner = FlightRunnerLargeEmitter(weather=..., source=..., cfg=cfg)
```

Fleet runners accept the same override via `FleetRunnerParams.config`.

## Discovery rules and common pitfalls

- **Import-time registration.** `@register` only runs when the module is
  imported. If your custom step lives in a package that PyNeats doesn't
  import, import it explicitly from your application entry point.
- **Overwriting.** Registering a name that already exists is allowed but
  emits a `RuntimeWarning` — useful for tests, risky in production.
- **Signature compatibility.** Implementations are structurally checked
  against the `Protocol`. Missing or mismatched methods surface as
  `AttributeError`/`TypeError` at `__call__` time, not at registration.
- **Parameters passed via `RunnerConfig.params`** are forwarded verbatim as
  `**params` to the constructor. Extra keys raise `TypeError`.

## Why a registry rather than direct imports?

Keeping runners free of concrete step references means:

- **Swappable implementations** — switch parser from NEATS JSON to ADS-B by
  changing one string in `RunnerConfig`.
- **Configuration-driven pipelines** — YAML/JSON configs can select steps
  by name without generating code.
- **Third-party extensions** — a plugin package can ship new steps without
  forking PyNeats.
