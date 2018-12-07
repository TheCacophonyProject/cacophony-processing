from operator import itemgetter
from itertools import groupby

MIN_TRACK_CONFIDENCE = 0.85
FALSE_POSITIVE = "false-positive"
UNIDENTIFIED = "unidentified"

MESSAGE = 'message'
CONFIDENCE = 'confidence'

def calculate_tags(tracks, conf):
  # No tracks found so tag as FALSE_POSITIVE
  tags = {}
  if not tracks:
    tags[FALSE_POSITIVE] = {CONFIDENCE: MIN_TRACK_CONFIDENCE}
    return tags

  toBeTagged, unknowns = findSignificantTracks(tracks, conf)

  if unknowns > 0:
    tags[UNIDENTIFIED] = {CONFIDENCE: MIN_TRACK_CONFIDENCE}

  sortedTags = sorted(toBeTagged, key=itemgetter("label"))
  for label, label_tracks in groupby(toBeTagged, itemgetter("label")):
    confidence = max(t[CONFIDENCE] for t in label_tracks)
    tags[label] = {CONFIDENCE: confidence}

  if len(tags) == 0:
    tags[FALSE_POSITIVE] = {CONFIDENCE: MIN_TRACK_CONFIDENCE}

  print(tags)
  return tags


def findSignificantTracks(tracks, conf):
  toBeTagged = []
  unknowns = 0

  for track in tracks:
    if track['confidence'] < conf.min_confidence:
      # what about if only just false positive
      track[MESSAGE] = "Very low confidence - ignore"
    elif track["label"] == FALSE_POSITIVE and track["clarity"] > conf.min_tag_clarity / 2:
      continue
    else:
      tag = False
      if track[CONFIDENCE] < conf.min_tag_confidence:
        track[MESSAGE] = "Low confidence - no tag"
      elif track["clarity"] < conf.min_tag_clarity:
        track[MESSAGE] = "Confusion between two classes (similar confidence)"
      elif track["average_novelty"] > conf.max_tag_novelty:
        track[MESSAGE] = "High novelty"
      else:
        toBeTagged.append(track)
        tag = True

      if tag:
        continue
      elif track["num_frames"] < conf.min_frames:
        track[MESSAGE] = "Short track"
      else:
        unknowns += 1
  return (toBeTagged, unknowns)
