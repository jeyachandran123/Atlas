"""
Cross-cutting platform infrastructure — not specific to documents.

Home for concerns every future UnityWorks AI subsystem (Document AI, Vision
AI, Coding AI, Repository AI, Meeting AI, Automation AI) shares: capability
self-description and feature flag evaluation. Nothing here knows about
documents, parsers, or knowledge objects — document_platform CONSUMES this
package, never the other way around.
"""
