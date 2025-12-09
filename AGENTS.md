Only run non `network` marked tests. E.g. `uv run pytest -m "not network"`.
Only run tests when ready for release or when completely baffled by a bug. 

This framework does NOT use asyncio. Check the docs for details on how to execute async code with the bare flowno EventLoop.

Use `java -jar ./formal-verification/tla2tools.jar` to run TLA+ model checking on the generated specs.
`java -jar ./formal-verification/tla2tools.jar ./formal-verification/specs/YourSpec.tla -config ./formal-verification/specs/YourSpec.cfg`

To generate LaTeX/PDF documentation from TLA+ specs, use:
java -cp ./formal-verification/tla2tools.jar tla2tex.TLA -latexCommand pdflatex -latexOutputExt pdf ./formal-verification/specs/YourSpec.tla