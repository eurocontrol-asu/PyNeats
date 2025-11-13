# Architecture

## Repository Layout

pyneats/
├── src/
│ └── pyneats/
│ ├── core/ # shared types, constants, protocols
│ ├── adapters/ # wrappers around external libs
│ ├── steps/ # pipeline stages
│ ├── pipeline/ # orchestration
│ ├── io/ # data I/O
│ ├── cli/ # command-line interface
│ └── utils/ # misc utilities
└── tests/
└── examples/