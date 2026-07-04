"""This package carries the build-time embedded payloads produced by the
release pipeline: ``build_info.json`` (a JSON object with exactly the
string keys "product", "package_version", "adapter_version",
"build_date", and "image_tag") and ``operator_doc.md`` (UTF-8 Markdown,
rendered from the single documentation source that also produces the
installed man and info pages). The two payload files are generated at
build time and are absent in a source checkout; their absence at
runtime is a packaging defect surfaced by the reader as an explicit
error.
"""
