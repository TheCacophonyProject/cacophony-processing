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


def calculate_tags(tracks, conf):
    # No tracks found so tag as FALSE_POSITIVE
    multiple = None
    tags = {}
    if not tracks:
        return tracks, tags
    clear_tracks, unclear_tracks, tags = get_significant_tracks(tracks, conf)
    multiple_confidence = calculate_multiple_animal_confidence(
        clear_tracks + unclear_tracks
    )
    if multiple_confidence > conf.min_confidence:
        tags[MULTIPLE] = {"event": MULTIPLE, CONFIDENCE: multiple_confidence}
    return tracks, tags


def calc_track_movement(track):
    if "positions" not in track:
        return 0
    mid_xs = []
    mid_ys = []
    for frame in track["positions"]:
        mid_xs.append((frame["x"] + frame["width"]) / 2)
        mid_ys.append((frame["y"] + frame["height"]) / 2)
    delta_x = max(mid_xs) - min(mid_xs)
    delta_y = max(mid_ys) - min(mid_ys)
    return max(delta_x, delta_y)


def is_significant_track(track, confidence, conf):
    if track["num_frames"] < conf.min_frames:
        track[MESSAGE] = "Short track"
        return False
    if confidence > conf.min_confidence:
        return True
    if calc_track_movement(track) > 50:
        return True
    track[MESSAGE] = "Low movement and poor confidence - ignore"
    return False


def prediction_is_clear(prediction, conf):
    conf_thresh = conf.min_tag_confidence
    if prediction[LABEL] == FALSE_POSITIVE:
        conf_thresh = conf.min_tag_clarity_secondary
    if prediction[CONFIDENCE] < conf_thresh:
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
            if is_significant_track(track, prediction.get(CONFIDENCE, 0), conf):
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
    all_tracks.sort(key=by_start_time)
    for i in range(0, len(all_tracks) - 1):
        for j in range(i + 1, len(all_tracks)):
            if all_tracks[j]["start_s"] + 1 < all_tracks[i]["end_s"]:
                this_conf = min(all_tracks[i][CONFIDENCE], all_tracks[j][CONFIDENCE])
                confidence = max(confidence, this_conf)
    return confidence
