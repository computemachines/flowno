import sphinx

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "Flowno"
copyright = "2025, Tyler Parker"
author = "Tyler Parker"
release = "0.1.0"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.doctest",
    "sphinx.ext.autosummary",
    "plantweb.directive",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
]

plantweb_defaults = {
    # "server": "http://127.0.0.1:8080/",
}

intersphinx_mapping = {
    "python": ("https://docs.python.org/3.10", None),
}

templates_path = ["_templates"]
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_css_files = ["custom.css"]

rst_prolog = f"""
.. |sphinx_version| replace:: {sphinx.__version__}
"""

autosummary_generate = False

autodoc_mock_imports = [
    "flowno.nodes",
]
