# cacophony-processing

This is a server side component that runs alongside the Cacophony
Project API, performing post-upload processing tasks.

Currently it supports the following kinds of processing:

1. Feeding uploaded CPTV (Cacophony Project Thermal Video) files to an
   external classifier. The tags and MP4 files generated by the
   classifier are passed back to the API server. This is handled by
   thermal_processing.py.
2. Converting uploaded audio files to MP3 format (if required). This
   is handled by audio_processing.py
3. Running the Cacophony Project
   [audio-analysis](https://github.com/TheCacophonyProject/audio-analysis/)
   tool over uploaded audio recordings.

## Configuration

cacophony-processing requires access to the Cacophony API's
`fileProcessing` API as well as direct access to the API's backing
object store. Copy `processing_TEMPLATE.yaml` to `processing.yaml` and
edit as appropriate.

The processing.yaml file may either be placed in /etc/cacophony or in
the same directory as the code.

## Running on a developer machine

* Start cacophony-api locally.
* Copy processing_TEMPLATE.yaml to processing.yaml and edit as appropriate.
* Create and activate a virtualenv. This virtualenv must use Python 3.5 or later.
* Install dependencies: `pip install -r requirements.txt`
* Run `python main.py`

## Creating releases

* Ensure all changes have been merged and are pulled into the local copy.
* Tag the release (starting with a "v"), e.g.: `git tag -a v1.2.3 -m "1.2.3 release"`
* Push the tag to Github, e.g.: `git push origin v1.2.3`
* TravisCI will run the tests, create a release package and create a
  [Github Release](https://github.com/TheCacophonyProject/cacophony-processing/releases)


## Running on a server

### Install Processing

Install latest package from https://github.com/TheCacophonyProject/cacophony-processing/releases
`sudo dpkg -i cacophony-processing_<version>_amd64.deb`

### Update the config at ``/etc/cacophony/processing.yaml`

You will need a super user account to the browse platform at api_url endpoint in which the processing results will be uploaded under.

```
api_url: "https://api.cacophony.org.nz"
api_user: test-user
api_password: test-password
```

After configuring the config you can restart the service
`systemctl restart cacophony-processing`

Or you can run it manually
`/usr/bin/cacophony-processing.pex -m main`

### Specifying number of workers
You can configure how many workers and of which type in the config under

For IR:

```
ir:
  tracking_workers: 0
  analyse_workers: 0
```
For Thermal:

```
thermal:
    thermal_workers: 2
    tracking_workers: 2  
```

For Audio:

```
audio:
    analysis_workers: 2
```

For Trail Camera:

```
trailcam:
  trail_workers: 1
```

### Docker
The workers use docker image to run their jobs, by default they will be set up to use latest image, but you can specify the exact image to run and commands to run on them
inside `/etc/cacophony/processing.yaml`
thermal/ir images https://hub.docker.com/repository/docker/cacophonyproject/classifier
audio images https://hub.docker.com/repository/docker/cacophonyproject/audio-analysis
trailcam images https://hub.docker.com/r/zaandahl/megadetector
