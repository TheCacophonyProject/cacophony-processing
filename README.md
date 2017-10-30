# cacophony-processing

This is a server side component that runs alongside the Cacophony
Project API, performing post-upload processing tasks.

Currently, the only processing task implemented is the generation of
MP4 files from Cacophony Project Thermal Video (CPTV) files. Other
tasks will be added soon.

## Configuration

cacophony-processing requires access to the Cacophony API's
`fileProcessing` API as well as direct access to the API's backing
object store. Copy `config_TEMPLATE.yaml` to `config.yaml` and edit as
appropriate.

## Installing & Running

The processing component requires Python 3. Use of virtualenv is highly recommended.

Install dependencies like this:

```
pip install -r requirements.txt
```

Run like this:

```
python processing.py
```
