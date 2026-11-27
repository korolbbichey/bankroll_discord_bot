"""
Builds paste.html, the text to paste into the bot's long description on top.gg, from description.html.

top.gg reads the description as Markdown: lines indented by 4+ spaces and line breaks inside the HTML add
big empty gaps. So the markup is joined into one line with no indentation; the CSS stays as it is.
Run: python docs/topgg/build.py
"""

import re
from pathlib import Path

HERE = Path(__file__).parent

source = (HERE / "description.html").read_text(encoding="utf-8")
style, markup = source.split("</style>", 1)
markup = re.sub(r">\s+<", "><", markup.strip())  # nothing between tags
markup = re.sub(r"\s*\n\s*", " ", markup)          # line breaks inside text become spaces
(HERE / "paste.html").write_text(style + "</style>\n" + markup + "\n", encoding="utf-8")
print(f"paste.html: {len(style) + len(markup):,} characters")
