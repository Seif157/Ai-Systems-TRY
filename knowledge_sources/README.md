# Approved knowledge source boundary

This documents the intended boundary; it is not a discovery root and contains no ingestible
production document or catalog.

```text
knowledge_sources/
├── product/
│   └── hr/                 # Reviewed employee-facing product guidance
└── customer_policy/
    └── <controlled source> # Future tenant-controlled integration
```

Every source must be explicitly cataloged and pinned by raw SHA-256. The adapter never scans these
directories. Every path component is inspected without following links; symbolic links, Windows
junctions, and all reparse points are forbidden. Reading uses one identity-validated, bounded file
handle. These checks run in Linux and Windows CI, although they cannot eliminate every underlying
filesystem TOCTOU race. Do not place customer policies, personal data, or internal schema documents here.
Specifically, `docs/database/hr` must not be copied into employee-facing knowledge. Synthetic
fixtures belong under tests and temporary test directories only.
