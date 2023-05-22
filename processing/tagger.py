from operator import itemgetter
from itertools import groupby

DEFAULT_CONFIDENCE = 0.85
FALSE_POSITIVE = "false-positive"
UNIDENTIFIED = "unidentified"
MULTIPLE = "multiple animals"
TAG = "tag"
CLARITY = "clarity"
LABEL = "label"
PREDICTIONS = "predictions"

MESSAGE = "message"
CONFIDENCE = "confidence"
MASTER_TAG = "master_tag"


def calculate_tags(tracks, conf):
    # No tracks found so tag as FALSE_POSITIVE
    multiple = None
    tags = {}
    if not tracks:
        return tracks, tags
    clear_tracks, unclear_tracks, tags = get_significant_tracks(tracks, conf)

    return tracks, tags


def prediction_is_clear(prediction, conf):
    if prediction[CONFIDENCE] < conf.min_tag_confidence:
        prediction[MESSAGE] = "Low confidence - no tag"
        return False
    if prediction[CLARITY] < conf.min_tag_clarity:
        prediction[MESSAGE] = "Confusion between two classes (similar confidence)"
        return False
    if prediction.get("average_novelty", 0) > conf.max_tag_novelty:
        prediction[MESSAGE] = "High novelty"
        return False
    return True


def get_significant_tracks(tracks, conf):
    clear_tracks = []
    unclear_tracks = []
    tags = {}

    for track in tracks:
        track[CONFIDENCE] = 0
        has_clear_prediction = False
        for prediction in track[PREDICTIONS]:
            if conf.ignore_tags is not None and prediction[LABEL] in conf.ignore_tags:
                continue

            confidence = prediction.get(CONFIDENCE, 0)
            track[CONFIDENCE] = max(track.get(CONFIDENCE, 0), confidence)
            if prediction_is_clear(prediction, conf):
                has_clear_prediction = True
                tag = prediction[LABEL]
                prediction[TAG] = tag
                if tag in tags:
                    tags[tag][CONFIDENCE] = max(tags[tag][CONFIDENCE], confidence)
                else:
                    tags[tag] = {CONFIDENCE: confidence}

            else:
                tags[UNIDENTIFIED] = {CONFIDENCE: DEFAULT_CONFIDENCE}
                prediction[TAG] = UNIDENTIFIED

        if has_clear_prediction:
            clear_tracks.append(track)
        else:
            unclear_tracks.append(track)
    return (clear_tracks, unclear_tracks, tags)


def by_start_time(elem):
    return elem["start_s"]


def calculate_multiple_animal_confidence(all_tracks):
    """check that lower overlapping confidence is above threshold"""
    confidence = 0
    animal_tracks = []
    for t in all_tracks:
        tag = t.get(MASTER_TAG)
        if tag is None:
            continue
        tag = tag.get(TAG)
        if tag is not None and tag not in [FALSE_POSITIVE, UNIDENTIFIED]:
            animal_tracks.append(t)
    animal_tracks.sort(key=by_start_time)

    for i in range(0, len(animal_tracks) - 1):
        for j in range(i + 1, len(animal_tracks)):
            if animal_tracks[j]["start_s"] + 1 < animal_tracks[i]["end_s"]:
                this_conf = min(
                    animal_tracks[i][CONFIDENCE], animal_tracks[j][CONFIDENCE]
                )
                confidence = max(confidence, this_conf)
    return confidence
