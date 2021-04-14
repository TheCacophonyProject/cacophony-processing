from operator import itemgetter
from itertools import groupby

DEFAULT_CONFIDENCE = 0.85
FALSE_POSITIVE = "false-positive"
UNIDENTIFIED = "unidentified"
MULTIPLE = "multiple animals"
TAG = "tag"
CLARITY = "clarity"
LABEL = "label"

MESSAGE = "message"
CONFIDENCE = "confidence"
FALSE_POSITIVE_TAG = {"event": "false positive", CONFIDENCE: DEFAULT_CONFIDENCE}


def calculate_tags(tracks, conf):
    # No tracks found so tag as FALSE_POSITIVE
    if not tracks:
        return tracks, {}
    clear_animals, unclear_animals, tags = get_significant_tracks(tracks, conf)

    if len(tags) == 0:
        tags[FALSE_POSITIVE] = FALSE_POSITIVE_TAG
    else:
        multiple_confidence = calculate_multiple_animal_confidence(
            clear_animals + unclear_animals
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
        coords = frame[1]
        mid_xs.append((coords[0] + coords[2]) / 2)
        mid_ys.append((coords[1] + coords[3]) / 2)
    delta_x = max(mid_xs) - min(mid_xs)
    delta_y = max(mid_ys) - min(mid_ys)
    return max(delta_x, delta_y)


def is_significant_track(track, conf):
    if track["num_frames"] < conf.min_frames:
        track[MESSAGE] = "Short track"
        return False
    if track["confidence"] > conf.min_confidence:
        return True
    if calc_track_movement(track) > 50:
        return True
    track[MESSAGE] = "Low movement and poor confidence - ignore"
    return False


def prediction_is_clear(prediction, conf):
    if track[CONFIDENCE] < conf.min_tag_confidence:
        return False, "Low confidence - no tag"
    elif track[CLARITY] < conf.min_tag_clarity:
        return False, "Confusion between two classes (similar confidence)"
    elif track["average_novelty"] > conf.max_tag_novelty:
        return False, "High novelty"
    return True, None


def get_significant_tracks(tracks, conf):
    clear_animals = []
    unclear_animals = []
    tags = {}
    for track in tracks:
        for model_prediction in track["model_predictions"]:
            if (
                conf.ignore_tags is not None
                and model_prediction[LABEL] in conf.ignore_tags
            ):
                continue
            if is_significant_track(model, conf):
                if (
                    model[LABEL] == FALSE_POSITIVE
                    and model[CLARITY] > conf.min_tag_clarity_secondary
                ):
                    continue

                if track_is_clear(model, conf):
                    clear_animals.append(track)
                    model[TAG] = model[LABEL]
                    tag = model[LABEL]
                    if TAG in tags:
                        tags[tag][CONFIDENCE] = max(
                            tags[tag][CONFIDENCE], track[CONFIDENCE]
                        )
                    else:
                        tags[tag] = {CONFIDENCE: track[CONFIDENCE]}

                else:
                    unclear_animals.append(track)
                    tags[UNIDENTIFIED] = {CONFIDENCE: DEFAULT_CONFIDENCE}
                    track[TAG] = UNIDENTIFIED
    return (clear_animals, unclear_animals, tags)


def by_start_time(elem):
    return elem["start_s"]


def calculate_multiple_animal_confidence(all_animals):
    """ check that lower overlapping confidence is above threshold """
    confidence = 0
    all_animals.sort(key=by_start_time)
    for i in range(0, len(all_animals) - 1):
        for j in range(i + 1, len(all_animals)):
            if all_animals[j]["start_s"] + 1 < all_animals[i]["end_s"]:
                this_conf = min(all_animals[i][CONFIDENCE], all_animals[j][CONFIDENCE])
                confidence = max(confidence, this_conf)
    return confidence
