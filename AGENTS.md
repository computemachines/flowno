Only run non `network` marked tests. E.g. `uv run pytest -m "not network"`.
Only run tests when ready for release or when completely baffled by a bug. 

This framework does NOT use asyncio. Check the docs for details on how to execute async code with the bare flowno EventLoop.

Use TLC to run TLA+ model checking on the generated specs (from the root directory):
`java -cp formal-verification/tla2tools.jar:formal-verification/specs/modules:formal-verification/specs/models tlc2.TLC -config formal-verification/specs/model-tests/YourSpec.cfg formal-verification/specs/models/YourSpec.tla`

To generate LaTeX/PDF documentation from TLA+ specs, use:
java -cp ./formal-verification/tla2tools.jar tla2tex.TLA -latexCommand pdflatex -latexOutputExt pdf ./formal-verification/specs/YourSpec.tla