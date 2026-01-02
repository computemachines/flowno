Only run non `network` marked tests. E.g. `uv run pytest -m "not network"`.
Only run tests when ready for release or when completely baffled by a bug. 

DO NOT USE MCP SERVERS for TLA+/PlusCal work. Use the command line (the `tla2tools.jar` commands below) for PlusCal transpilation, SANY parsing, and TLC runs.

This framework does NOT use asyncio. Check the docs for details on how to execute async code with the bare flowno EventLoop.

Use the tla2tools.jar to transpile pluscal (from the root directory):
`java -cp formal-verification/tla2tools.jar pcal.trans ./formal-verification/pluscal-exploration/JoinExample_A_EventLoopHandler.tla`

Use TLC to run TLA+ model checking on the generated specs (from the root directory):
`java -cp formal-verification/tla2tools.jar:formal-verification/specs/modules:formal-verification/specs/models tlc2.TLC -config formal-verification/specs/model-tests/SharedConfigName.cfg formal-verification/specs/models/Topology_Config_ImplEx.tla`

Example: `java -cp formal-verification/tla2tools.jar:formal-verification/specs/modules:formal-verification/specs/models tlc2.TLC -config formal-verification/specs/model-tests/CyclicMonoFlow.cfg formal-verification/specs/models/Triangle3_Mono_CyclicEx.tla`

To generate LaTeX/PDF documentation from TLA+ specs, use:
`java -cp ./formal-verification/tla2tools.jar tla2tex.TLA -latexCommand pdflatex -latexOutputExt pdf ./formal-verification/specs/models/Topology_Config_ImplEx.tla`