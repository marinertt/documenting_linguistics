"""Render the notebook as the GitHub Pages homepage without executing cells."""
from pathlib import Path
import shutil
import nbformat
from nbconvert import HTMLExporter

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / '_site'


def build():
    notebook = nbformat.read(ROOT / 'test.ipynb', as_version=4)
    nbformat.validate(notebook)
    # Add page navigation only to the rendered copy, leaving the notebook intact.
    notebook.cells.insert(0, nbformat.v4.new_markdown_cell(
        '# Fieldnotes · Corpus Studio\n\n'
        'A notebook for exploring linguistic annotations, searching a corpus, '
        'and building a contextual lexicon.\n\n'
        '[Download this notebook](test.ipynb) · '
        '[View the project on GitHub](https://github.com/marinertt/documenting_linguistics)\n\n'
        '**Notebook view:** this page shows code and saved outputs. '
        'Download the notebook and run it locally to execute Python cells.\n\n---'
    ))
    exporter = HTMLExporter(template_name='lab')
    exporter.embed_images = True
    body, _ = exporter.from_notebook_node(notebook, resources={
        'metadata': {'name': 'Fieldnotes · Corpus Studio', 'path': str(ROOT)}
    })
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / 'index.html').write_text(body, encoding='utf-8')
    (OUTPUT / '.nojekyll').write_text('', encoding='utf-8')
    shutil.copyfile(ROOT / 'test.ipynb', OUTPUT / 'test.ipynb')
    print(f'Built {OUTPUT / "index.html"} ({len(notebook.cells)-1} notebook cells)')


if __name__ == '__main__':
    build()
