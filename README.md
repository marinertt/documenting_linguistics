# Fieldnotes · Corpus Studio

A local interface for exploring the EAF corpus and building a contextual lexicon.

Run from this folder:

```sh
venv/bin/python app.py
```

Open http://127.0.0.1:8765 in your browser. Stop the server with Ctrl+C.

- Search original-language transcripts or Portuguese translations. Search is whole-word by default; enable “Match within words” for partial matches.
- Browse parallel transcript/translation passages and expand their annotation details.
- Choose “Collect a word” or “Add a word” to save an entry and matching examples. Selected passage text can prefill the word field. Sentence translations are context, not automatic lexical definitions.
- Open “My lexicon” to filter entries, inspect examples, or edit meanings and notes. Entries use the same `data/lexicon.json` file as the notebook.
- Load the matching audio recording locally and use “Listen to segment” for bounded playback. Audio stays in the browser. The repository does not include the recording; intervals come from the EAF and are segment-level.

The UI currently loads `data/eaf_example.eaf`; it uses the existing Python search, DataFrame and lexicon modules. No additional packages beyond the existing environment are required. The server binds to localhost and is intended for one local user.

Validation: `venv/bin/python -m unittest test_app -v` and `node --check web/app.js`.

## Volume connections

The **Volume** page mounts read-only storage connections inside Fieldnotes (not operating-system drives). It supports local folder paths, S3 buckets/prefixes using an AWS profile or default credential chain, and Azure Blob containers using DefaultAzureCredential. Connections are saved in `data/volumes.json` only after a successful listing. Credentials are not collected or saved by the app.

Browse folders and paginated file listings, or unmount a connection without deleting its files. Mounting does not yet import EAF files or change the active corpus. Cloud connections require an existing authorized sign-in and permission to list the selected bucket/container.

Install cloud dependencies with `venv/bin/pip install -r requirements-volumes.txt`.

Authentication references: [AWS credentials](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html), [Azure Blob listing and authentication](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blobs-list-python).

Selecting Volume opens the right-hand Mounted sources panel. Expand mounted roots and folders to browse; click a file to open a document preview in the main pane. Text (including EAF, PFSX, XML and JSON) is displayed literally, with previews also available for common images, PDF and audio. Other binary documents offer a download. Previews are limited to 10 MB and do not change the active corpus.
