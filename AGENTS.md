Only run non `network` marked tests. For example:

    pytest -m "not network"

Run type checks with basedpyright only on the new `typecheck` directory:

    basedpyright typecheck