from operator import itemgetter
from itertools import groupby

DEFAULT_CONFIDENCE = 0.85
FALSE_POSITIVE = "false-positive"
UNIDENTIFIED = "unidentified"
MULTIPLE = "multiple animals"
STATUS = "status"
CLARITY = "clarity"

MESSAGE = 'message'
CONFIDENCE = 'confidence'
FALSE_POSITIVE_TAG = {"event": "false positive", CONFIDENCE: DEFAULT_CONFIDENCE}


def calculate_tags(tracks, conf):
  # No tracks found so tag as FALSE_POSITIVE
  tags = {}
  if not tracks:
    tags[FALSE_POSITIVE] = FALSE_POSITIVE_TAG
    return tags

  clear_animals, unclear_animals = find_significant_tracks(tracks, conf)

  # definites
  for label, label_tracks in groupby(clear_animals, itemgetter("label")):
    confidence = max(t[CONFIDENCE] for t in label_tracks)
    tags[label] = {CONFIDENCE: confidence}

  # unknowns
  for track in unclear_animals:
    # Reduce clarity required when there is clear existing track with same label
    if track[CLARITY] > conf.min_tag_clarity_secondary and track["label"] in tags:
      continue
    else:
      # there might be something else going on here...
      tags[UNIDENTIFIED] = {CONFIDENCE: DEFAULT_CONFIDENCE}
      break

  if len(tags) == 0:
    tags[FALSE_POSITIVE] = FALSE_POSITIVE_TAG
  else:
    multiple_confidence = calculate_multiple_animal_confidence(clear_animals + unclear_animals)
    if multiple_confidence > conf.min_confidence:
      tags[MULTIPLE] = {"event": MULTIPLE, CONFIDENCE: multiple_confidence}

  return tags


def find_significant_tracks(tracks, conf):
  clear_animals = []
  unclear_animals = []

  for track in tracks:
    if track['confidence'] < conf.min_confidence:
      track[MESSAGE] = "Very low confidence - ignore"
    # Use secondary clarity here as guessing it is less likely to confuse a false positive with an animal.
    elif track["label"] == FALSE_POSITIVE and track[CLARITY] > conf.min_tag_clarity_secondary:
      continue
    else:
      if track[CONFIDENCE] < conf.min_tag_confidence:
        track[MESSAGE] = "Low confidence - no tag"
      elif track[CLARITY] < conf.min_tag_clarity:
        track[MESSAGE] = "Confusion between two classes (similar confidence)"
      elif track["average_novelty"] > conf.max_tag_novelty:
        track[MESSAGE] = "High novelty"
      else:
        clear_animals.append(track)
        track[STATUS] = 'tag'
        continue

      if track["num_frames"] < conf.min_frames:
        # If we have clear identication keep the track, else ignore it if it is short
        track[MESSAGE] = "Short track"
      else:
        unclear_animals.append(track)
        track[STATUS] = 'unknown'
  return (clear_animals, unclear_animals)

def by_start_time(elem):
    return elem["start_s"]

def calculate_multiple_animal_confidence(all_animals):
  confidence = 0
  all_animals.sort(key=by_start_time)
  for i in range(0, len(all_animals) - 1):
    for j in range(i+1, len(all_animals)):
      if all_animals[j]["start_s"] < all_animals[i]["end_s"]:
        this_conf = min(all_animals[i][CONFIDENCE], all_animals[j][CONFIDENCE])
        confidence = max(confidence, this_conf)
  return confidence

