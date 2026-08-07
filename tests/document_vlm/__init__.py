"""Tests for the Document VLM port, its adapters, and the extraction pipeline.

Every test in this package runs without an API key, without a network, and
without a GPU. That is a requirement rather than a convenience: a suite that
needs live NVIDIA access is a suite that stops being run, and an extraction
pipeline whose failure modes are only exercised in production is one whose
failure modes are discovered there.
"""
