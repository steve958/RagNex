#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

from .pdf_parser import PlainParser
from .pdf_parser import RAGFlowPdfParser as PdfParser

__all__ = ["PdfParser", "PlainParser"]

# Optional parsers: these require extra third-party dependencies.
try:
    from .docx_parser import RAGFlowDocxParser as DocxParser

    __all__.append("DocxParser")
except Exception:  # pragma: no cover
    DocxParser = None  # type: ignore

try:
    from .excel_parser import RAGFlowExcelParser as ExcelParser

    __all__.append("ExcelParser")
except Exception:  # pragma: no cover
    ExcelParser = None  # type: ignore

try:
    from .ppt_parser import RAGFlowPptParser as PptParser

    __all__.append("PptParser")
except Exception:  # pragma: no cover
    PptParser = None  # type: ignore

try:
    from .html_parser import RAGFlowHtmlParser as HtmlParser

    __all__.append("HtmlParser")
except Exception:  # pragma: no cover
    HtmlParser = None  # type: ignore

try:
    from .json_parser import RAGFlowJsonParser as JsonParser

    __all__.append("JsonParser")
except Exception:  # pragma: no cover
    JsonParser = None  # type: ignore

try:
    from .markdown_parser import MarkdownElementExtractor
    from .markdown_parser import RAGFlowMarkdownParser as MarkdownParser

    __all__.extend(["MarkdownParser", "MarkdownElementExtractor"])
except Exception:  # pragma: no cover
    MarkdownParser = None  # type: ignore
    MarkdownElementExtractor = None  # type: ignore

try:
    from .txt_parser import RAGFlowTxtParser as TxtParser

    __all__.append("TxtParser")
except Exception:  # pragma: no cover
    TxtParser = None  # type: ignore

