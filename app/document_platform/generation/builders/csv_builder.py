"""CSV builder (pandas). CSV is flat — the first table wins; multiple
tables are concatenated with a blank separator row and a name banner."""
from __future__ import annotations

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
            import pandas as pd

            tables = model.tables
            if not tables:
                # No tabular content — degrade honestly to a two-column
                # key/value dump of sections rather than an empty file.
                rows = [(s.heading, " ".join(s.paragraphs + s.bullets))
                        for s in model.sections]
                df = pd.DataFrame(rows, columns=["section", "content"])
                return df.to_csv(index=False, lineterminator="\n").encode("utf-8-sig")

            buf = io.StringIO()
            for i, table in enumerate(tables):
                if len(tables) > 1:
                    buf.write(f"# {table.name}\n")
                width = len(table.headers)
                normalized = [
                    (row + [""] * width)[:width] for row in table.rows
                ]
                df = pd.DataFrame(normalized, columns=table.headers)
                df.to_csv(buf, index=False, lineterminator="\n")
                if i < len(tables) - 1:
                    buf.write("\n")
            return buf.getvalue().encode("utf-8-sig")
        except BuildError:
            raise
        except Exception as e:
            raise BuildError(f"CSV build failed: {e}") from e
