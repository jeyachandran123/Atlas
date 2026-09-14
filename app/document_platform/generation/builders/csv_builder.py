"""CSV builder (stdlib csv). CSV is flat — the first table wins; multiple
tables are concatenated with a blank separator row and a name banner.

Writing rows needs no dataframe: the stdlib writer quotes exactly as pandas'
``to_csv`` did (minimal quoting), and keeping CSV off pandas means a missing
or broken pandas install can never take CSV generation down with it."""
from __future__ import annotations

import csv
import io

from app.document_platform.generation.builders.base import AbstractFileBuilder, BuildError
from app.document_platform.generation.content_model import ContentModel


class CsvBuilder(AbstractFileBuilder):
    format_name = "csv"
    extension = "csv"
    content_type = "text/csv"
    features = frozenset({"tables", "flat"})

    def build(self, model: ContentModel) -> bytes:
        try:
            buf = io.StringIO()
            writer = csv.writer(buf, lineterminator="\n")

            tables = model.tables
            if not tables:
                # No tabular content — degrade honestly to a two-column
                # key/value dump of sections rather than an empty file.
                writer.writerow(["section", "content"])
                for s in model.sections:
                    writer.writerow([s.heading, " ".join(s.paragraphs + s.bullets)])
                return buf.getvalue().encode("utf-8-sig")

            for i, table in enumerate(tables):
                if len(tables) > 1:
                    buf.write(f"# {table.name}\n")
                width = len(table.headers)
                writer.writerow(table.headers)
                for row in table.rows:
                    writer.writerow((row + [""] * width)[:width])
                if i < len(tables) - 1:
                    buf.write("\n")
            return buf.getvalue().encode("utf-8-sig")
        except BuildError:
            raise
        except Exception as e:
            raise BuildError(f"CSV build failed: {e}") from e
